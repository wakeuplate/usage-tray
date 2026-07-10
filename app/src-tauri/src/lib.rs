use std::collections::VecDeque;
use std::fs::File;
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};

use tauri::image::Image;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager};
use tauri_plugin_autostart::ManagerExt;
use tauri_plugin_positioner::{Position, WindowExt};

const COLLECTOR_RELATIVE_PATH: &str = "collectors\\collect_usage_tray.py";
const HISTORY_RELATIVE_PATH: &str = "collectors\\history_snapshot.py";
const TELEGRAM_RELATIVE_PATH: &str = "collectors\\telegram_bridge.py";
const TRAY_ID: &str = "usage-tray-tray";

fn python_command() -> Command {
    let mut command = Command::new("python");
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        // CREATE_NO_WINDOW: a windowless release build would otherwise flash a
        // console window every time a Python helper is spawned.
        command.creation_flags(0x0800_0000);
    }
    command
}

#[tauri::command]
async fn collect_usage(app: AppHandle) -> Result<serde_json::Value, String> {
    tauri::async_runtime::spawn_blocking(move || collect_usage_blocking(app))
        .await
        .map_err(|_| "Collector task stopped unexpectedly.".to_string())?
}

fn collect_usage_blocking(app: AppHandle) -> Result<serde_json::Value, String> {
    let project_root = project_root_from_app(&app)?;
    let collector_path = project_root.join(COLLECTOR_RELATIVE_PATH);

    let output = python_command()
        .arg(&collector_path)
        .arg("--timeout-sec")
        .arg("20")
        .output()
        .map_err(|error| format!("Failed to start collector: {error}"))?;

    if !output.status.success() {
        return Err(format!(
            "Collector exited with status {}.",
            output.status.code().unwrap_or(-1)
        ));
    }

    let payload = serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("Collector returned invalid JSON: {error}"))?;

    let _ = save_history_snapshot(&app, &payload);
    let _ = process_telegram_alerts(&app, &payload);
    Ok(payload)
}

fn run_python_json_script(
    app: &AppHandle,
    relative_path: &str,
    action: &str,
    payload: &serde_json::Value,
) -> Result<serde_json::Value, String> {
    let project_root = project_root_from_app(app)?;
    let script_path = project_root.join(relative_path);
    let input = serde_json::to_vec(payload).map_err(|_| "Unable to prepare script input.".to_string())?;

    let mut child = python_command()
        .arg(script_path)
        .arg(action)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|error| format!("Failed to start helper script: {error}"))?;

    let mut stdin = child
        .stdin
        .take()
        .ok_or_else(|| "Unable to open helper input.".to_string())?;
    stdin
        .write_all(&input)
        .map_err(|_| "Unable to write helper input.".to_string())?;
    drop(stdin);

    let output = child
        .wait_with_output()
        .map_err(|_| "Unable to finish helper script.".to_string())?;

    let parsed = serde_json::from_slice::<serde_json::Value>(&output.stdout)
        .map_err(|_| "Helper script returned invalid JSON.".to_string())?;

    if output.status.success() {
        return Ok(parsed);
    }

    let message = parsed["error"]
        .as_str()
        .unwrap_or("Helper script failed.")
        .to_string();
    Err(message)
}

fn save_history_snapshot(app: &AppHandle, payload: &serde_json::Value) -> Result<(), String> {
    let project_root = project_root_from_app(app)?;
    let history_script = project_root.join(HISTORY_RELATIVE_PATH);
    let history_path = history_output_path(app)?.join("snapshots.jsonl");
    let input = serde_json::to_vec(payload)
        .map_err(|_| "Unable to prepare history snapshot.".to_string())?;

    let mut child = python_command()
        .arg(history_script)
        .arg("--output")
        .arg(history_path)
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|_| "Unable to start history writer.".to_string())?;

    let mut stdin = child
        .stdin
        .take()
        .ok_or_else(|| "Unable to open history input.".to_string())?;
    stdin
        .write_all(&input)
        .map_err(|_| "Unable to write history input.".to_string())?;
    drop(stdin);

    let status = child
        .wait()
        .map_err(|_| "Unable to finish history write.".to_string())?;
    if !status.success() {
        return Err("History writer failed.".to_string());
    }

    Ok(())
}

fn history_output_path(app: &AppHandle) -> Result<PathBuf, String> {
    if let Some(app_data) = std::env::var_os("APPDATA") {
        return Ok(PathBuf::from(app_data).join("UsageTray"));
    }

    app.path()
        .app_data_dir()
        .map_err(|_| "Unable to resolve history directory.".to_string())
}

// One-time migration from the pre-rename data directory (%APPDATA%\LimitLens).
fn migrate_legacy_app_dir() {
    let Some(app_data) = std::env::var_os("APPDATA") else {
        return;
    };
    let base = PathBuf::from(app_data);
    let legacy = base.join("LimitLens");
    let current = base.join("UsageTray");
    if legacy.is_dir() && !current.exists() {
        let _ = std::fs::rename(&legacy, &current);
    }
}

fn process_telegram_alerts(app: &AppHandle, snapshot: &serde_json::Value) -> Result<(), String> {
    run_python_json_script(
        app,
        TELEGRAM_RELATIVE_PATH,
        "process-alerts",
        &serde_json::json!({ "snapshot": snapshot }),
    )
    .map(|_| ())
}

#[tauri::command]
fn get_alert_settings(app: AppHandle) -> Result<serde_json::Value, String> {
    run_python_json_script(
        &app,
        TELEGRAM_RELATIVE_PATH,
        "load-settings",
        &serde_json::json!({}),
    )
}

#[tauri::command]
fn save_alert_settings(
    app: AppHandle,
    payload: serde_json::Value,
) -> Result<serde_json::Value, String> {
    run_python_json_script(
        &app,
        TELEGRAM_RELATIVE_PATH,
        "save-settings",
        &payload,
    )
}

#[tauri::command]
fn discover_telegram_chat(app: AppHandle) -> Result<serde_json::Value, String> {
    run_python_json_script(
        &app,
        TELEGRAM_RELATIVE_PATH,
        "discover-chat",
        &serde_json::json!({}),
    )
}

#[tauri::command]
fn send_telegram_test(app: AppHandle) -> Result<serde_json::Value, String> {
    run_python_json_script(
        &app,
        TELEGRAM_RELATIVE_PATH,
        "send-test",
        &serde_json::json!({}),
    )
}

#[tauri::command]
fn read_history(app: AppHandle, limit: Option<usize>) -> Result<Vec<serde_json::Value>, String> {
    let history_path = history_output_path(&app)?.join("snapshots.jsonl");
    if !history_path.exists() {
        return Ok(Vec::new());
    }

    let max_rows = limit.unwrap_or(500).clamp(1, 2_000);
    let file = File::open(history_path).map_err(|_| "Unable to open history.".to_string())?;
    let mut rows = VecDeque::with_capacity(max_rows);

    for line in BufReader::new(file).lines() {
        let line = line.map_err(|_| "Unable to read history.".to_string())?;
        if line.trim().is_empty() {
            continue;
        }
        let Ok(snapshot) = serde_json::from_str::<serde_json::Value>(&line) else {
            continue;
        };
        if rows.len() == max_rows {
            rows.pop_front();
        }
        rows.push_back(snapshot);
    }

    Ok(rows.into())
}

#[tauri::command]
fn update_tray_tooltip(app: AppHandle, summary: String) -> Result<(), String> {
    let clean: String = summary
        .chars()
        .filter(|character| !character.is_control())
        .take(120)
        .collect();
    if clean.trim().is_empty() {
        return Err("Tooltip summary was empty.".to_string());
    }

    set_tray_tooltip(&app, clean)
}

fn set_tray_tooltip(app: &AppHandle, summary: String) -> Result<(), String> {
    let tray = app
        .tray_by_id(TRAY_ID)
        .ok_or_else(|| "Tray icon is unavailable.".to_string())?;
    tray.set_tooltip(Some(summary))
        .map_err(|_| "Unable to update tray tooltip.".to_string())
}

fn tooltip_summary(payload: &serde_json::Value) -> String {
    fn remaining(payload: &serde_json::Value, agent: &str) -> String {
        payload["agents"][agent]["windows"]["five_hour"]["remaining_percent"]
            .as_f64()
            .map(|value| format!("{value:.0}%"))
            .unwrap_or_else(|| "-".to_string())
    }

    format!(
        "Codex 剩餘 {} | Claude 剩餘 {}",
        remaining(payload, "codex"),
        remaining(payload, "claude")
    )
}

fn project_root_from_app(app: &AppHandle) -> Result<PathBuf, String> {
    if cfg!(debug_assertions) {
        return PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(|app_dir| app_dir.parent())
            .map(PathBuf::from)
            .ok_or_else(|| "Unable to resolve development project directory.".to_string());
    }

    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|error| format!("Unable to resolve resource directory: {error}"))?;
    Ok(resource_dir)
}

fn show_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        if window
            .move_window_constrained(Position::TrayCenter)
            .is_err()
        {
            let _ = window.move_window(Position::BottomRight);
        }
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn toggle_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        if window.is_visible().unwrap_or(false) {
            let _ = window.hide();
        } else {
            show_main_window(app);
        }
    }
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            show_main_window(app);
        }))
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .on_window_event(|window, event| {
            if window.label() == "main" {
                if let tauri::WindowEvent::Focused(false) = event {
                    let _ = window.hide();
                }
            }
        })
        .setup(|app| {
            migrate_legacy_app_dir();
            let _ = app.autolaunch().enable();
            app.handle().plugin(tauri_plugin_positioner::init())?;

            let show = MenuItem::with_id(app, "show", "Show UsageTray", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;
            let icon = Image::from_bytes(include_bytes!("../icons/32x32.png"))?;
            let app_handle = app.handle().clone();

            TrayIconBuilder::with_id(TRAY_ID)
                .icon(icon)
                .tooltip("UsageTray")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(move |app, event| match event.id().as_ref() {
                    "show" => toggle_main_window(app),
                    "quit" => app.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(move |tray, event| {
                    tauri_plugin_positioner::on_tray_event(tray.app_handle(), &event);
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        toggle_main_window(&app_handle);
                    }
                })
                .build(app)?;

            let background_app = app.handle().clone();
            std::thread::spawn(move || loop {
                std::thread::sleep(std::time::Duration::from_secs(300));
                if let Ok(payload) = collect_usage_blocking(background_app.clone()) {
                    let _ = set_tray_tooltip(&background_app, tooltip_summary(&payload));
                }
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            collect_usage,
            discover_telegram_chat,
            get_alert_settings,
            read_history,
            save_alert_settings,
            send_telegram_test,
            update_tray_tooltip
        ])
        .run(tauri::generate_context!())
        .expect("error while running UsageTray");
}

