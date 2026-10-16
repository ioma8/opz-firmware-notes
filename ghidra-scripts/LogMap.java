import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.scalar.Scalar;
import java.io.*;

/** Map log call sites to the source file / line / format they use.
 *  For every CALL to the logger inside [start,end), walk back over the preceding instructions
 *  and resolve any address-shaped scalar (fused X-format immediate) plus any raw hi/lo pair in
 *  the preceding bytes, then print the NUL-terminated string at each resolved address. */
public class LogMap extends GhidraScript {
    @Override protected void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter w = new PrintWriter(new FileWriter(a[0]));
        Address logger = toAddr(a[1]);
        Address p = toAddr(a[2]);
        Address end = toAddr(a[3]);
        Listing L = currentProgram.getListing();
        Memory mem = currentProgram.getMemory();
        int n = 0, hits = 0;
        while (p.compareTo(end) < 0 && n < 500000) {
            Instruction ins = L.getInstructionAt(p);
            if (ins == null) { disassemble(p); ins = L.getInstructionAt(p); }
            if (ins == null) { p = p.add(2); continue; }
            if (ins.getFlowType().isCall() && ins.toString().contains(logger.toString())) {
                hits++;
                Function f = getFunctionContaining(p);
                w.println(String.format("== call at %s  in %s", p,
                        f == null ? "(no fn)" : f.getName() + "@" + f.getEntryPoint()));
                // the logger's line number is the value loaded into R1 immediately before the call
                String line = "?";
                Address r1 = p;
                for (int k = 0; k < 24; k++) {
                    Instruction prev = L.getInstructionBefore(r1);
                    if (prev == null) break;
                    r1 = prev.getAddress();
                    if (prev.toString().startsWith("LdImmToReg R1 =")) {
                        for (Object o : prev.getOpObjects(1))
                            if (o instanceof Scalar) line = Long.toString(((Scalar) o).getUnsignedValue());
                        break;
                    }
                }
                w.println("   line argument (from R1): " + line);
                // walk back up to 24 instructions, resolving address-shaped scalars
                Address q = p;
                for (int k = 0; k < 24; k++) {
                    Instruction prev = L.getInstructionBefore(q);
                    if (prev == null) break;
                    q = prev.getAddress();
                    for (int op = 0; op < prev.getNumOperands(); op++)
                        for (Object o : prev.getOpObjects(op)) {
                            if (!(o instanceof Scalar)) continue;
                            long v = ((Scalar) o).getUnsignedValue();
                            if (v >= 0x80000000L && v < 0x82000000L) w.println("   " + q + "  " + prev + "   -> " + str(mem, v));
                        }
                    // raw hi/lo pair inside this instruction's bytes
                    try {
                        int len = prev.getLength();
                        byte[] b = new byte[len];
                        mem.getBytes(q, b);
                        for (int i = 0; i + 4 <= len; i++) {
                            int hi = (b[i] & 0xff) | ((b[i+1] & 0xff) << 8);
                            if (hi < 0x8000 || hi > 0x8101) continue;
                            for (int j = i + 2; j + 2 <= len; j++) {
                                int lo = (b[j] & 0xff) | ((b[j+1] & 0xff) << 8);
                                long v = ((long) hi << 16) | lo;
                                if (v >= 0x80000000L && v < 0x82000000L)
                                    w.println("   " + q + "  (raw pair) -> " + str(mem, v));
                            }
                        }
                    } catch (Exception e) { }
                }
            }
            p = ins.getMaxAddress().add(1); n++;
        }
        w.println("scanned " + n + " instructions, " + hits + " log call sites");
        w.close();
    }

    String str(Memory mem, long v) {
        StringBuilder sb = new StringBuilder();
        try {
            for (int i = 0; i < 72; i++) {
                byte b = mem.getByte(toAddr(v + i));
                if (b == 0) break;
                if (b < 0x20 || b > 0x7e) { sb.append('?'); break; }
                sb.append((char) b);
            }
        } catch (Exception e) { return "(no mem)"; }
        return "\"" + sb + "\"";
    }
}
