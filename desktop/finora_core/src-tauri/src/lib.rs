mod session;
mod project_export;

/// Meta/AI credentials remain server-side. Desktop sessions use user-scoped Windows encryption.
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![session::load_session, session::save_session, project_export::save_project_export])
        .run(tauri::generate_context!())
        .expect("failed to start FINORA CORE");
}
