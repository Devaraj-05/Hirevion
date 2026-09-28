// Release builds are GUI-only; debug builds keep a console for logs.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    hirevion_desktop_lib::run();
}
