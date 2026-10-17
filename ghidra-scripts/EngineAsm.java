// Assemble source lines with the program's own SLEIGH assembler and print the bytes.
// Usage: EngineAsm.java <outfile> <srcfile> <baseaddr>
// Each non-empty, non-comment line of <srcfile> is assembled at a consecutive address.
// This is how engine/DSP code can be authored without an external toolchain: the bytes
// come from the same language definition that Ghidra disassembles with, so the
// encode/decode round trip is by construction.
import ghidra.app.script.GhidraScript;
import ghidra.app.plugin.assembler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.listing.Instruction;
import java.io.*;
import java.nio.file.*;

public class EngineAsm extends GhidraScript {
    @Override protected void run() throws Exception {
        String[] args = getScriptArgs();
        PrintWriter w = new PrintWriter(new FileWriter(args[0]));
        Assembler asm;
        try {
            asm = Assemblers.getAssembler(currentProgram);
        } catch (Throwable t) {
            w.println("NO ASSEMBLER: " + t);
            w.close();
            return;
        }
        w.println("assembler=" + asm.getClass().getName());
        String src = "";
        if (args.length > 1) src = new String(Files.readAllBytes(Paths.get(args[1])));
        Address a = toAddr(Long.decode(args.length > 2 ? args[2] : "0x0"));
        StringBuilder bytes = new StringBuilder();
        int ok = 0, bad = 0;
        for (String raw : src.split("\n")) {
            String line = raw.trim();
            if (line.isEmpty() || line.startsWith(";") || line.startsWith("#")) continue;
            try {
                InstructionIterator it = asm.assemble(a, line);
                while (it.hasNext()) {
                    Instruction ins = it.next();
                    for (byte b : ins.getBytes()) bytes.append(String.format("%02x", b));
                    w.println(String.format("%s  %-34s -> %s", ins.getAddress(), line, ins.toString()));
                    a = a.add(ins.getLength());
                }
                ok++;
            } catch (Throwable t) {
                w.println("FAIL at " + a + " : " + line + "  -- " + t);
                bad++;
            }
        }
        w.println("assembled=" + ok + " failed=" + bad);
        w.println("BYTES: " + bytes);
        w.close();
    }
}
