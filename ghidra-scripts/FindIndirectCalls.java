import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import java.io.*;

// Enumerate every indirect call in the image, with the instructions leading up to it.
//
// The interesting thing about a dispatch site is not the call itself but what the preceding handful of
// instructions loaded and from which struct offset, so each hit prints its context. Indirect calls are rare
// in the OP-Z OS image, which makes this a short list rather than a haystack.
//
// Args: <out-file> [context-instructions]
public class FindIndirectCalls extends GhidraScript {
    @Override protected void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter w = new PrintWriter(new FileWriter(a[0]));
        int ctx = a.length > 1 ? Integer.decode(a[1]) : 8;
        Listing L = currentProgram.getListing();
        int hits = 0;
        for (Instruction ins : L.getInstructions(true)) {
            String mn = ins.getMnemonicString();
            if (!mn.equalsIgnoreCase("Call") && !mn.equalsIgnoreCase("Jump")) continue;
            String ops = ins.toString();
            if (ops.indexOf('(') < 0) continue;                 // direct target: not what we want
            Function f = getFunctionContaining(ins.getAddress());
            w.println("=== " + ins.getAddress() + "  " + ops
                      + "   in " + (f == null ? "(no function)" : f.getName() + "@" + f.getEntryPoint()));
            Address p = ins.getAddress();
            for (int i = 0; i < ctx; i++) {
                Instruction prev = L.getInstructionBefore(p);
                if (prev == null) break;
                w.println("      " + prev.getAddress() + "  " + prev.toString());
                p = prev.getAddress();
            }
            hits++;
        }
        w.println("total indirect call/jump sites: " + hits);
        w.close();
    }
}
