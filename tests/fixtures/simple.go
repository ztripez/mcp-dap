package main

import "fmt"

func greet(name string) string {
	message := fmt.Sprintf("Hello, %s!", name)
	fmt.Println(message)
	return message
}

func add(a, b int) int {
	result := a + b
	return result
}

func main() {
	name := "World"
	greeting := greet(name)
	_ = greeting
	sum := add(2, 3)
	fmt.Printf("Sum: %d\n", sum)
}
