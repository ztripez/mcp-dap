#!/usr/bin/env python3
"""Simple test program for debugging."""


def greet(name: str) -> str:
    """Return a greeting message."""
    message = f"Hello, {name}!"
    return message


def main() -> None:
    """Main entry point."""
    names = ["Alice", "Bob", "Charlie"]
    for name in names:
        greeting = greet(name)
        print(greeting)


if __name__ == "__main__":
    main()
