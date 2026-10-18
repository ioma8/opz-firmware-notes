import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import java.io.*;

// Enumerate every indirect call/jump, including ones the analyzer never disassembled.
//
// Walking the Listing is not sufficient: whole regions of opz.ldr have no instructions in the listing, so
// a listing-based scan silently misses call sites (the engine init call at 0x8012d41a was one of them).
// Blackfin encodes these as 16-bit ProgCtrl forms with signature 0 at bits 8-15, so this scans the bytes
// of every executable block for those halfwords, disassembles each candidate, and keeps the ones that come
// back as an indirect Call/Jump.
//
// Args: <out-file> [context-instructions]
public class FindIndirectCalls extends GhidraScript {
    @Override protected void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter w = new PrintWriter(new FileWriter(a[0]));
        int ctx = a.length > 1 ? Integer.decode(a[1]) : 10;
        Listing L = currentProgram.getListing();
        Memory mem = currentProgram.getMemory();
        int hits = 0, candidates = 0;
        for (MemoryBlock b : mem.getBlocks()) {
            if (!b.isInitialized() || !b.isExecute()) continue;
            Address start = b.getStart(), end = b.getEnd();
            for (Address p = start; p.compareTo(end) < 0; p = p.add(2)) {
                int h;
                try { h = mem.getShort(p) & 0xFFFF; } catch (Exception e) { break; }
                // ProgCtrl: bits 8-15 zero; opc 5..8 are the indirect JUMP/CALL forms
                if ((h & 0xFF00) != 0) continue;
                int opc = (h >> 4) & 0xF;
                if (opc < 5 || opc > 8) continue;
                candidates++;
                Instruction ins = L.getInstructionAt(p);
                if (ins == null) { disassemble(p); ins = L.getInstructionAt(p); }
                if (ins == null) continue;
                String mn = ins.getMnemonicString();
                if (!mn.equalsIgnoreCase("Call") && !mn.equalsIgnoreCase("Jump")) continue;
                if (ins.toString().indexOf('(') < 0) continue;
                Function f = getFunctionContaining(p);
                w.println("=== " + p + "  " + ins.toString()
                          + "   in " + (f == null ? "(no function)" : f.getName() + "@" + f.getEntryPoint()));
                Address q = p;
                for (int i = 0; i < ctx; i++) {
                    Instruction prev = L.getInstructionBefore(q);
                    if (prev == null) break;
                    w.println("      " + prev.getAddress() + "  " + prev.toString());
                    q = prev.getAddress();
                }
                hits++;
            }
        }
        w.println("candidates scanned: " + candidates + ", indirect call/jump sites: " + hits);
        w.close();
    }
}
