import com.microsoft.java.debug.core.adapter.*;
import com.microsoft.java.debug.core.adapter.ISourceLookUpProvider.MethodInvocation;
import com.microsoft.java.debug.core.JavaBreakpointLocation;
import com.microsoft.java.debug.core.protocol.IProtocolServer;
import com.microsoft.java.debug.core.protocol.Types;
import com.sun.jdi.*;
import io.reactivex.Observable;

import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.function.Consumer;

/**
 * Minimal standalone DAP server for Java debugging.
 * Uses java-debug-core with basic providers to run as a stdio DAP adapter.
 */
public class StandaloneLauncher {

    public static void main(String[] args) {
        ProviderContext context = new ProviderContext();

        context.registerProvider(IVirtualMachineManagerProvider.class,
            (IVirtualMachineManagerProvider) Bootstrap::virtualMachineManager);

        context.registerProvider(ISourceLookUpProvider.class,
            new BasicSourceLookUpProvider());

        context.registerProvider(IHotCodeReplaceProvider.class,
            new NoOpHotCodeReplaceProvider());

        context.registerProvider(IEvaluationProvider.class,
            new NoOpEvaluationProvider());

        context.registerProvider(ICompletionsProvider.class,
            new NoOpCompletionsProvider());

        ProtocolServer server = new ProtocolServer(System.in, System.out,
            (IDebugAdapterFactory) ps -> new DebugAdapter(ps, context));

        server.run();
    }

    /** Basic source lookup that resolves files from the filesystem. */
    static class BasicSourceLookUpProvider implements ISourceLookUpProvider {
        @Override
        public boolean supportsRealtimeBreakpointVerification() { return false; }

        @Override
        public String[] getFullyQualifiedName(String uri, int[] lines, int[] columns) {
            // Convert file URI to class name by reading the package declaration
            String[] result = new String[lines.length];
            try {
                Path path = Path.of(uri.startsWith("file:") ? new java.net.URI(uri) : Path.of(uri).toUri());
                String source = Files.readString(path);
                String pkg = "";
                for (String line : source.split("\\n")) {
                    String trimmed = line.trim();
                    if (trimmed.startsWith("package ")) {
                        pkg = trimmed.substring(8).replace(";", "").trim();
                        break;
                    }
                    if (trimmed.startsWith("import ") || trimmed.startsWith("public ")
                            || trimmed.startsWith("class ")) {
                        break;
                    }
                }
                String fileName = path.getFileName().toString();
                String className = fileName.endsWith(".java")
                        ? fileName.substring(0, fileName.length() - 5)
                        : fileName;
                String fqn = pkg.isEmpty() ? className : pkg + "." + className;
                Arrays.fill(result, fqn);
            } catch (Exception e) {
                Arrays.fill(result, "");
            }
            return result;
        }

        @Override
        public JavaBreakpointLocation[] getBreakpointLocations(
                String source, Types.SourceBreakpoint[] bps) {
            JavaBreakpointLocation[] locs = new JavaBreakpointLocation[bps.length];
            for (int i = 0; i < bps.length; i++) {
                locs[i] = new JavaBreakpointLocation(bps[i].line, -1);
            }
            return locs;
        }

        @Override
        public String getSourceFileURI(String fqn, String sourcePath) {
            return sourcePath != null ? sourcePath : fqn;
        }

        @Override
        public String getSourceContents(String uri) {
            try {
                Path path = Path.of(uri.startsWith("file:") ? new java.net.URI(uri) : Path.of(uri).toUri());
                return Files.readString(path);
            } catch (Exception e) {
                return "";
            }
        }

        @Override
        public List<MethodInvocation> findMethodInvocations(String uri, int line) {
            return Collections.emptyList();
        }
    }

    /** No-op hot code replace provider (hot reload not supported standalone). */
    static class NoOpHotCodeReplaceProvider implements IHotCodeReplaceProvider {
        @Override public void onClassRedefined(Consumer<List<String>> c) {}
        @Override public CompletableFuture<List<String>> redefineClasses() {
            return CompletableFuture.completedFuture(Collections.emptyList());
        }
        @Override public Observable<HotCodeReplaceEvent> getEventHub() {
            return Observable.empty();
        }
    }

    /** No-op evaluation provider (expression eval not supported standalone). */
    static class NoOpEvaluationProvider implements IEvaluationProvider {
        @Override public boolean isInEvaluation(ThreadReference t) { return false; }
        @Override public CompletableFuture<Value> evaluate(String e, ThreadReference t, int d) {
            return CompletableFuture.failedFuture(
                new UnsupportedOperationException("Expression evaluation requires JDT"));
        }
        @Override public CompletableFuture<Value> evaluate(String e, ObjectReference o, ThreadReference t) {
            return CompletableFuture.failedFuture(
                new UnsupportedOperationException("Expression evaluation requires JDT"));
        }
        @Override public CompletableFuture<Value> evaluateForBreakpoint(
                com.microsoft.java.debug.core.IEvaluatableBreakpoint bp, ThreadReference t) {
            return CompletableFuture.failedFuture(
                new UnsupportedOperationException("Expression evaluation requires JDT"));
        }
        @Override public CompletableFuture<Value> invokeMethod(
                ObjectReference o, String n, String s, Value[] v, ThreadReference t, boolean b) {
            return CompletableFuture.failedFuture(
                new UnsupportedOperationException("Method invocation requires JDT"));
        }
        @Override public void clearState(ThreadReference t) {}
    }

    /** No-op completions provider. */
    static class NoOpCompletionsProvider implements ICompletionsProvider {
        @Override public List<Types.CompletionItem> codeComplete(
                StackFrame f, String e, int l, int c) {
            return Collections.emptyList();
        }
    }
}
