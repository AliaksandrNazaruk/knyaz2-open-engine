// Завести функции там, где Ghidra их не нашла.
//
// Ghidra делает функцию по CALL. Точки входа, на которые смотрят ТОЛЬКО
// указатели в данных, она пропускает — и в konung2.exe это не мелочь:
//
//   0x462E90   таблица обработчиков разговора, 76 указателей. Диспетчер
//              0x435F44 прыгает по ней, CALL'ов на обработчики нет вовсе,
//              и 37 из 76 не стали функциями. Из-за этого у половины
//              диалоговых действий не было кода, чтобы их перенести.
//   0x42F22C   оконная процедура: единственная ссылка — поле lpfnWndProc
//              структуры WNDCLASSA (VA 0x42EBD0). Весь разбор сообщений и
//              ввода лежит именно здесь.
//
// Скрипт идёт тремя проходами: именованные таблицы, именованные адреса и
// общий подметатель — все dword'ы инициализированной памяти, которые
// показывают в секцию кода мимо известных функций.
//
// Запускать ПЕРЕД анализом (-preScript), чтобы автоанализ разобрал заведённое:
//   analyzeHeadless <проект> knyaz2 -process konung2.exe \
//       -scriptPath tools/ghidra \
//       -preScript MakeMissingFunctions.java \
//       -postScript ExportDecompiled.java <куда>
//
//@category Knyaz2
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;

import java.util.ArrayList;
import java.util.List;
import java.util.TreeSet;

public class MakeMissingFunctions extends GhidraScript {

    //: Секция кода BEGTEXT. Нижняя граница поднята на 0x100: в данных
    //: попадаются мелкие числа вроде 0x410002, и это не адреса.
    private static final long CODE_LO = 0x410100L;
    private static final long CODE_HI = 0x44B800L;

    //: Таблица обработчиков разговора: адрес и сколько в ней записей
    //: (konung2/quests.py: HANDLERS_VA, HANDLERS).
    private static final long HANDLER_TABLE = 0x462E90L;
    private static final int HANDLER_COUNT = 76;

    //: Точки входа, на которые ссылается не таблица, а одиночное поле.
    private static final long[] SINGLE = { 0x42F22CL };

    private int made = 0;
    private int already = 0;
    private int failed = 0;

    @Override
    public void run() throws Exception {
        println("== завожу пропущенные функции ==");

        List<Long> targets = new ArrayList<>();

        // 1. Таблица обработчиков разговора.
        for (int i = 0; i < HANDLER_COUNT; i++) {
            long value = Integer.toUnsignedLong(getInt(toAddr(HANDLER_TABLE + i * 4L)));
            if (value >= CODE_LO && value < CODE_HI) {
                targets.add(value);
            }
        }
        println("из таблицы 0x462E90 взято адресов: " + targets.size());

        // 2. Одиночные ссылки (оконная процедура).
        for (long address : SINGLE) {
            targets.add(address);
        }

        // 3. Общий подметатель: все dword'ы данных, показывающие в код.
        TreeSet<Long> swept = sweepDataPointers();
        println("подметатель нашёл адресов кода без функции: " + swept.size());
        targets.addAll(swept);

        TreeSet<Long> unique = new TreeSet<>(targets);
        for (long address : unique) {
            make(toAddr(address));
        }

        println("== заведено " + made + ", уже были " + already + ", не вышло " + failed + " ==");
    }

    //: Все четырёхбайтовые значения инициализированной памяти, которые
    //: показывают в секцию кода мимо тела известной функции.
    private TreeSet<Long> sweepDataPointers() throws Exception {
        TreeSet<Long> found = new TreeSet<>();
        Memory memory = currentProgram.getMemory();
        boolean bigEndian = currentProgram.getLanguage().isBigEndian();
        for (MemoryBlock block : memory.getBlocks()) {
            if (!block.isInitialized()) {
                continue;
            }
            int size = (int) Math.min(block.getSize(), Integer.MAX_VALUE);
            byte[] bytes = new byte[size];
            memory.getBytes(block.getStart(), bytes);
            for (int at = 0; at + 4 <= size; at += 4) {
                long value = bigEndian ? readBig(bytes, at) : readLittle(bytes, at);
                if (value < CODE_LO || value >= CODE_HI) {
                    continue;
                }
                Address address = toAddr(value);
                if (getFunctionContaining(address) == null) {
                    found.add(value);
                }
            }
            if (monitor.isCancelled()) {
                break;
            }
        }
        return found;
    }

    private static long readLittle(byte[] bytes, int at) {
        return (bytes[at] & 0xFFL) | ((bytes[at + 1] & 0xFFL) << 8)
             | ((bytes[at + 2] & 0xFFL) << 16) | ((bytes[at + 3] & 0xFFL) << 24);
    }

    private static long readBig(byte[] bytes, int at) {
        return ((bytes[at] & 0xFFL) << 24) | ((bytes[at + 1] & 0xFFL) << 16)
             | ((bytes[at + 2] & 0xFFL) << 8) | (bytes[at + 3] & 0xFFL);
    }

    //: Завести одну функцию. Байты сначала разбираются в инструкции: на
    //: неразобранном месте createFunction не срабатывает.
    private void make(Address entry) {
        Function existing = getFunctionContaining(entry);
        if (existing != null) {
            if (existing.getEntryPoint().equals(entry)) {
                already += 1;
            } else {
                // Адрес попал в СЕРЕДИНУ чужой функции — заводить нечего,
                // иначе развалим уже разобранное.
                already += 1;
            }
            return;
        }
        if (getInstructionAt(entry) == null) {
            disassemble(entry);
        }
        Function created = createFunction(entry, null);
        if (created == null) {
            failed += 1;
            println("  не вышло: " + entry);
        } else {
            made += 1;
        }
    }
}
