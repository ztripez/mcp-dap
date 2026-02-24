// Simple Java test program for debugging
public class Simple {
    public static String greet(String name) {
        String message = "Hello, " + name + "!";
        System.out.println(message);
        return message;
    }

    public static int add(int a, int b) {
        int result = a + b;
        return result;
    }

    public static void main(String[] args) {
        String name = "World";
        String greeting = greet(name);
        int sum = add(2, 3);
        System.out.println("Sum: " + sum);
    }
}
