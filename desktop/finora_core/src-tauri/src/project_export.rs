use tauri_plugin_dialog::DialogExt;

/// The destination comes only from the native save picker, never from web content.
#[tauri::command]
pub async fn save_project_export(app: tauri::AppHandle, revision: u32, format: String, content: String) -> Result<bool, String> {
    let extension = match format.as_str() {
        "json" | "n8n" => "json",
        "svg" => "svg",
        _ => return Err("صيغة تصدير غير معروفة".into()),
    };
    if content.len() > 8 * 1024 * 1024 {
        return Err("المخطط أكبر من حجم التصدير المسموح".into());
    }
    let name = format!("finora-project-{revision}-{format}.{extension}");
    tauri::async_runtime::spawn_blocking(move || {
        let selected = app.dialog().file()
            .set_title("تصدير مخطط المشروع")
            .set_file_name(name)
            .add_filter("Project map", &[extension])
            .blocking_save_file();
        let Some(selected) = selected else { return Ok(false); };
        let mut path = selected.into_path().map_err(|_| "تعذر اختيار مكان الحفظ".to_string())?;
        if path.extension().is_none() { path.set_extension(extension); }
        if path.extension().and_then(|s| s.to_str()) != Some(extension) {
            return Err("اختر امتداد الملف المطابق لصيغة التصدير".into());
        }
        std::fs::write(path, content).map_err(|_| "تعذر حفظ المخطط في المكان المختار".to_string())?;
        Ok(true)
    }).await.map_err(|_| "تعذر فتح نافذة الحفظ".to_string())?
}
