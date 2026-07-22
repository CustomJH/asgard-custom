use std::{
    env,
    net::{TcpListener, TcpStream},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

struct DesktopServer(Mutex<Option<Child>>);

impl DesktopServer {
    fn stop(&self) {
        if let Ok(mut child) = self.0.lock() {
            if let Some(mut child) = child.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

impl Drop for DesktopServer {
    fn drop(&mut self) {
        self.stop();
    }
}

fn wait_for_server(port: u16, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if TcpStream::connect(("127.0.0.1", port)).is_ok() {
            return true;
        }
        thread::sleep(Duration::from_millis(80));
    }
    false
}

fn loopback_url(url: &str) -> bool {
    ["http://127.0.0.1:", "http://localhost:", "http://[::1]:"]
        .iter()
        .any(|prefix| url.starts_with(prefix))
}

fn asgard_program() -> PathBuf {
    if let Some(path) = env::var_os("ASGARD_EXECUTABLE") {
        return path.into();
    }
    let executable = if cfg!(windows) {
        "asgard.exe"
    } else {
        "asgard"
    };
    let mut candidates = vec![
        PathBuf::from("/opt/homebrew/bin").join(executable),
        PathBuf::from("/usr/local/bin").join(executable),
    ];
    if let Some(home) = env::var_os("HOME").or_else(|| env::var_os("USERPROFILE")) {
        let home = PathBuf::from(home);
        candidates.push(home.join(".local/bin").join(executable));
        candidates.push(
            home.join(".local/share/uv/tools/asgard/bin")
                .join(executable),
        );
        if let Ok(versions) = std::fs::read_dir(home.join(".local/share/mise/installs/python")) {
            candidates.extend(
                versions
                    .flatten()
                    .map(|entry| entry.path().join("bin").join(executable)),
            );
        }
    }
    candidates
        .into_iter()
        .find(|path| path.is_file())
        .unwrap_or_else(|| PathBuf::from(executable))
}

fn start_server() -> Result<(String, Child), String> {
    // ponytail: the bind/drop handoff has a tiny port race; pass an inherited FD if it is ever observed.
    let listener = TcpListener::bind(("127.0.0.1", 0)).map_err(|error| error.to_string())?;
    let port = listener
        .local_addr()
        .map_err(|error| error.to_string())?
        .port();
    drop(listener);

    let mut command = Command::new(asgard_program());
    command
        .args(["desktop", "--no-open", "--port", &port.to_string()])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    let root = env::var_os("ASGARD_DESKTOP_ROOT")
        .or_else(|| env::var_os("HOME"))
        .map(PathBuf::from)
        .or_else(|| env::current_dir().ok());
    if let Some(root) = root {
        command.current_dir(root);
    }
    let mut child = command.spawn().map_err(|error| error.to_string())?;
    if !wait_for_server(port, Duration::from_secs(12)) {
        let _ = child.kill();
        let _ = child.wait();
        return Err("Asgard Desktop server did not become ready".into());
    }
    Ok((format!("http://127.0.0.1:{port}/"), child))
}

fn main() {
    let app = tauri::Builder::default()
        .setup(|app| {
            let (url, child) = match env::var("ASGARD_DESKTOP_URL")
                .ok()
                .filter(|url| loopback_url(url))
            {
                Some(url) => (Some(url), None),
                None => match start_server() {
                    Ok((url, child)) => (Some(url), Some(child)),
                    Err(error) => {
                        eprintln!("Asgard Desktop: {error}");
                        (None, None)
                    }
                },
            };
            app.manage(DesktopServer(Mutex::new(child)));

            let target = match url {
                Some(url) => match url.parse() {
                    Ok(url) => WebviewUrl::External(url),
                    Err(_) => WebviewUrl::App("index.html".into()),
                },
                None => WebviewUrl::App("index.html".into()),
            };
            WebviewWindowBuilder::new(app, "main", target)
                .title("Asgard Desktop")
                .inner_size(1280.0, 820.0)
                .min_inner_size(900.0, 640.0)
                .build()?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build Asgard Desktop");
    app.run(|handle, event| {
        if matches!(
            event,
            tauri::RunEvent::Exit | tauri::RunEvent::ExitRequested { .. }
        ) {
            handle.state::<DesktopServer>().stop();
        }
    });
}

#[cfg(test)]
mod tests {
    use super::loopback_url;

    #[test]
    fn desktop_url_is_loopback_only() {
        assert!(loopback_url("http://127.0.0.1:8766/"));
        assert!(loopback_url("http://localhost:8766/"));
        assert!(!loopback_url("https://127.0.0.1:8766/"));
        assert!(!loopback_url("http://example.com:8766/"));
    }
}
