// Simple JavaScript test program for debugging
function greet(name) {
    const message = `Hello, ${name}!`;
    console.log(message);
    return message;
}

function add(a, b) {
    const result = a + b;
    return result;
}

const name = "World";
const greeting = greet(name);
const sum = add(2, 3);
console.log(`Sum: ${sum}`);
