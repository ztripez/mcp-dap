/// A simple Rust program for debugging tests.

fn greet(name: &str) -> String {
    let message = format!("Hello, {}!", name);
    message
}

fn main() {
    let names = vec!["Alice", "Bob", "Charlie"];
    for name in names {
        let greeting = greet(name);
        println!("{}", greeting);
    }
}
