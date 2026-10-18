use std::{path::PathBuf, sync::Mutex};
use tauri::Manager;

static SESSION_LOCK: Mutex<()> = Mutex::new(());
const MAX_SESSION_BYTES: usize = 64 * 1024;

fn session_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_local_data_dir()
        .map(|dir| dir.join("desktop-session.bin"))
        .map_err(|_| "Session directory unavailable".into())
}

#[tauri::command]
pub fn load_session(app: tauri::AppHandle) -> Result<Option<String>, String> {
    let _guard = SESSION_LOCK.lock().map_err(|_| "Session store unavailable")?;
    read_session(&session_path(&app)?)
}

#[tauri::command]
pub fn save_session(app: tauri::AppHandle, payload: Option<String>) -> Result<(), String> {
    let _guard = SESSION_LOCK.lock().map_err(|_| "Session store unavailable")?;
    write_session(&session_path(&app)?, payload.as_deref())
}

fn read_session(path: &std::path::Path) -> Result<Option<String>, String> {
    let bytes = match std::fs::read(path) {
        Ok(bytes) => bytes,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err("Could not read encrypted session".into()),
    };
    if bytes.is_empty() || bytes.len() > MAX_SESSION_BYTES + 4096 {
        return Err("Invalid encrypted session".into());
    }
    let plain = crypt(&bytes, false)?;
    String::from_utf8(plain)
        .map(Some)
        .map_err(|_| "Invalid session encoding".into())
}

fn write_session(path: &std::path::Path, payload: Option<&str>) -> Result<(), String> {
    let Some(payload) = payload else {
        return match std::fs::remove_file(path) {
            Ok(()) => Ok(()),
            Err(err) if err.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(_) => Err("Could not remove saved session".into()),
        };
    };
    if payload.is_empty() || payload.len() > MAX_SESSION_BYTES {
        return Err("Invalid session size".into());
    }
    // No plaintext is ever written. DPAPI binds the ciphertext to the current Windows user.
    let encrypted = crypt(payload.as_bytes(), true)?;
    let parent = path.parent().ok_or("Invalid session directory")?;
    std::fs::create_dir_all(parent).map_err(|_| "Could not create session directory")?;
    let temporary = path.with_extension("tmp");
    let result = (|| {
        use std::io::Write;
        let mut file = std::fs::File::create(&temporary).map_err(|_| "Could not write session")?;
        file.write_all(&encrypted).map_err(|_| "Could not write session")?;
        file.sync_all().map_err(|_| "Could not flush session")?;
        drop(file);
        replace_file(&temporary, path)
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary); // encrypted temporary only
    }
    result
}

#[cfg(windows)]
fn crypt(input: &[u8], protect: bool) -> Result<Vec<u8>, String> {
    use std::ptr::{null, null_mut};
    use windows_sys::Win32::{
        Foundation::LocalFree,
        Security::Cryptography::{
            CryptProtectData, CryptUnprotectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
        },
    };
    let blob = CRYPT_INTEGER_BLOB { cbData: input.len() as u32, pbData: input.as_ptr() as *mut u8 };
    let mut output = CRYPT_INTEGER_BLOB { cbData: 0, pbData: null_mut() };
    // SAFETY: input remains valid throughout the call; Windows allocates output with LocalAlloc.
    let ok = unsafe {
        if protect {
            CryptProtectData(&blob, null(), null(), null(), null(), CRYPTPROTECT_UI_FORBIDDEN, &mut output)
        } else {
            CryptUnprotectData(&blob, null_mut(), null(), null(), null(), CRYPTPROTECT_UI_FORBIDDEN, &mut output)
        }
    };
    if ok == 0 { return Err("Windows session encryption unavailable".into()); }
    // SAFETY: a successful DPAPI call yields cbData valid bytes, freed after copying.
    let bytes = unsafe {
        let bytes = std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec();
        if !protect {
            // Clear Windows' decrypted buffer before releasing it.
            for offset in 0..output.cbData as usize {
                std::ptr::write_volatile(output.pbData.add(offset), 0);
            }
        }
        LocalFree(output.pbData.cast());
        bytes
    };
    Ok(bytes)
}

#[cfg(windows)]
fn replace_file(from: &std::path::Path, to: &std::path::Path) -> Result<(), String> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::{MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH};
    let from: Vec<u16> = from.as_os_str().encode_wide().chain(Some(0)).collect();
    let to: Vec<u16> = to.as_os_str().encode_wide().chain(Some(0)).collect();
    // SAFETY: both buffers are null-terminated Windows paths and stay valid for the call.
    let ok = unsafe { MoveFileExW(from.as_ptr(), to.as_ptr(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) };
    if ok == 0 { Err("Could not replace saved session".into()) } else { Ok(()) }
}

#[cfg(not(windows))]
fn crypt(_input: &[u8], _protect: bool) -> Result<Vec<u8>, String> {
    Err("Secure session storage requires Windows".into())
}

#[cfg(not(windows))]
fn replace_file(_from: &std::path::Path, _to: &std::path::Path) -> Result<(), String> {
    Err("Secure session storage requires Windows".into())
}

#[cfg(all(test, windows))]
mod tests {
    use super::*;

    #[test]
    fn restart_rotation_and_logout_use_encrypted_file() {
        let directory = std::env::temp_dir().join(format!("finora-session-test-{}", std::process::id()));
        let path = directory.join("session.bin");
        let original = "{\"refreshToken\":\"test-only-old-token\"}";
        write_session(&path, Some(original)).unwrap();
        let disk = std::fs::read(&path).unwrap();
        assert!(!disk.windows(19).any(|part| part == b"test-only-old-token"));
        assert_eq!(read_session(&path).unwrap().as_deref(), Some(original));
        let rotated = "{\"refreshToken\":\"test-only-new-token\"}";
        write_session(&path, Some(rotated)).unwrap();
        assert_eq!(read_session(&path).unwrap().as_deref(), Some(rotated));
        write_session(&path, None).unwrap();
        assert_eq!(read_session(&path).unwrap(), None);
        std::fs::remove_dir(&directory).unwrap();
    }

    #[test]
    fn tampering_is_rejected() {
        let mut encrypted = crypt(b"test-only-session", true).unwrap();
        let last = encrypted.len() - 1;
        encrypted[last] ^= 1;
        assert!(crypt(&encrypted, false).is_err());
    }
}
