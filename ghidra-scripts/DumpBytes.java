import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;

// Print each instruction with the exact bytes it consumed, so an emulator can map encodings to
// behaviour from evidence instead of from a guess. Args: start, count.
public class DumpBytes extends GhidraScript {
    @Override protected void run() throws Exception {
        String[] a = getScriptArgs();
        Address p = toAddr(a[0]);
        int count = Integer.decode(a[1]);
        Listing L = currentProgram.getListing();
        Memory mem = currentProgram.getMemory();
        for (int i = 0; i < count; i++) {
            Instruction ins = L.getInstructionAt(p);
            if (ins == null) {
                if (!disassemble(p)) { println(String.format("%s  (bad)", p)); p = p.add(2); continue; }
                ins = L.getInstructionAt(p);
            }
            if (ins == null) { p = p.add(2); continue; }
            int len = ins.getLength();
            StringBuilder hex = new StringBuilder();
            for (int b = 0; b < len; b++) hex.append(String.format("%02x", mem.getByte(p.add(b)) & 0xFF));
            println(String.format("%s  %-16s %s", p, hex.toString(), ins.toString()));
            p = ins.getMaxAddress().add(1);
        }
    }
}
