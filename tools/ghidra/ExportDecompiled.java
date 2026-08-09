// Выгрузка декомпилированного кода konung2.exe для headless-режима Ghidra.
//
// Пишет по файлу на функцию (0x004xxxxx.c) и общий указатель index.json:
// адрес входа, имя, размер, кто вызывает и кого вызывает сама. Дальше по
// этому указателю мы ищем нужную подсистему, а не гадаем по дизассемблеру.
//
// Запуск (см. tools/ghidra_decompile.sh):
//   analyzeHeadless <проект> knyaz2 -import konung2.exe \
//       -scriptPath tools/ghidra -postScript ExportDecompiled.java <куда>
//
//@category Knyaz2
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.symbol.Reference;

import java.io.File;
import java.io.IOException;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Set;
import java.util.TreeSet;

public class ExportDecompiled extends GhidraScript {

    private static String json(String value) {
        StringBuilder out = new StringBuilder("\"");
        for (char c : value.toCharArray()) {
            switch (c) {
                case '"': out.append("\\\""); break;
                case '\\': out.append("\\\\"); break;
                case '\n': out.append("\\n"); break;
                case '\r': out.append("\\r"); break;
                case '\t': out.append("\\t"); break;
                default:
                    if (c < 0x20) {
                        out.append(String.format("\\u%04x", (int) c));
                    } else {
                        out.append(c);
                    }
            }
        }
        return out.append('"').toString();
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        File outDir = new File(args.length > 0 ? args[0] : "decompiled");
        File codeDir = new File(outDir, "functions");
        codeDir.mkdirs();

        DecompInterface decompiler = new DecompInterface();
        decompiler.setOptions(new DecompileOptions());
        decompiler.setSimplificationStyle("decompile");
        if (!decompiler.openProgram(currentProgram)) {
            println("декомпилятор не открыл программу: " + decompiler.getLastMessage());
            return;
        }

        List<String> entries = new ArrayList<>();
        FunctionIterator functions = currentProgram.getFunctionManager().getFunctions(true);
        int done = 0;
        int failed = 0;
        while (functions.hasNext() && !monitor.isCancelled()) {
            Function function = functions.next();
            Address entry = function.getEntryPoint();
            String address = String.format("0x%08x", entry.getOffset());

            String code = null;
            DecompileResults results = decompiler.decompileFunction(function, 90, monitor);
            if (results.decompileCompleted() && results.getDecompiledFunction() != null) {
                code = results.getDecompiledFunction().getC();
            }
            if (code == null) {
                failed += 1;
            } else {
                File target = new File(codeDir, address + ".c");
                try {
                    Files.write(target.toPath(), code.getBytes(StandardCharsets.UTF_8));
                } catch (IOException error) {
                    println("не записал " + target + ": " + error.getMessage());
                }
            }

            Set<String> callers = new TreeSet<>();
            for (Function caller : function.getCallingFunctions(monitor)) {
                callers.add(String.format("0x%08x", caller.getEntryPoint().getOffset()));
            }
            Set<String> callees = new TreeSet<>();
            for (Function callee : function.getCalledFunctions(monitor)) {
                callees.add(String.format("0x%08x", callee.getEntryPoint().getOffset()));
            }
            // Ссылки на данные — по ним ищутся таблицы движка.
            Set<String> data = new TreeSet<>();
            for (Address from : function.getBody().getAddresses(true)) {
                for (Reference reference : getReferencesFrom(from)) {
                    if (reference.getReferenceType().isData()) {
                        data.add(String.format("0x%08x", reference.getToAddress().getOffset()));
                    }
                }
            }

            StringBuilder record = new StringBuilder();
            record.append("{\"entry\": ").append(json(address));
            record.append(", \"name\": ").append(json(function.getName()));
            record.append(", \"size\": ").append(function.getBody().getNumAddresses());
            record.append(", \"decompiled\": ").append(code != null);
            record.append(", \"callers\": [");
            record.append(String.join(", ", quoteAll(callers)));
            record.append("], \"callees\": [");
            record.append(String.join(", ", quoteAll(callees)));
            record.append("], \"data\": [");
            record.append(String.join(", ", quoteAll(data)));
            record.append("]}");
            entries.add(record.toString());

            done += 1;
            if (done % 200 == 0) {
                println("функций разобрано: " + done);
            }
        }
        decompiler.dispose();

        try (PrintWriter index = new PrintWriter(new File(outDir, "index.json"), "UTF-8")) {
            index.println("[");
            index.println(String.join(",\n", entries));
            index.println("]");
        }
        println("готово: функций " + done + ", без кода " + failed + ", каталог " + outDir);
    }

    private List<String> quoteAll(Set<String> values) {
        List<String> quoted = new ArrayList<>();
        for (String value : values) {
            quoted.add(json(value));
        }
        Collections.sort(quoted);
        return quoted;
    }
}
