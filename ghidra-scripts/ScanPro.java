import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import java.io.*;
/** Disassemble a range and print only frame-establishing instructions (LINK / register pushes). */
public class ScanPro extends GhidraScript {
    @Override protected void run() throws Exception {
        String[] a = getScriptArgs();
        Address p = toAddr(a[0]);
        Address end = toAddr(a[1]);
        Listing L = currentProgram.getListing();
        int n = 0;
        while (p.compareTo(end) < 0 && n < 200000) {
            Instruction ins = L.getInstructionAt(p);
            if (ins == null) { disassemble(p); ins = L.getInstructionAt(p); }
            if (ins == null) { p = p.add(2); continue; }
            String s = ins.toString();
            if (s.contains("LINK") || s.contains("[--SP]")) println(p + "  " + s);
            p = ins.getMaxAddress().add(1); n++;
        }
        println("scanned " + n + " instructions");
    }
}
