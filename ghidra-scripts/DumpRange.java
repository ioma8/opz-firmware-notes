import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

public class DumpRange extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] a = getScriptArgs();
        Address start = toAddr(a[0]);
        int count = Integer.decode(a[1]);
        Listing L = currentProgram.getListing();
        Address p = start;
        for (int i=0; i<count; i++) {
            Instruction ins = L.getInstructionAt(p);
            if (ins == null) { if(!disassemble(p)) { println(p+"  (bad)"); p=p.add(2); continue; } ins = L.getInstructionAt(p); }
            if (ins == null) { p=p.add(2); continue; }
            println(String.format("%s  %-40s", p, ins.toString()));
            p = ins.getMaxAddress().add(1);
        }
    }
}
