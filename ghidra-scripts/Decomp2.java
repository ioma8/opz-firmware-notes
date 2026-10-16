import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import java.io.*;
public class Decomp2 extends GhidraScript {
    @Override protected void run() throws Exception {
        DecompInterface di=new DecompInterface();
        di.setOptions(new DecompileOptions());
        di.openProgram(currentProgram);
        PrintWriter w=new PrintWriter(new FileWriter(getScriptArgs()[0]));
        for(int i=1;i<getScriptArgs().length;i++){
            Address a=toAddr(getScriptArgs()[i]);
            Function f=getFunctionContaining(a);
            if(f==null){ disassemble(a); f=createFunction(a,null); }
            if(f==null){ w.println("=== no function at "+a+" ==="); continue; }
            w.println("===== "+f.getName()+" @ "+f.getEntryPoint()+" =====");
            DecompileResults r=di.decompileFunction(f,240,monitor);
            if(r.getDecompiledFunction()!=null) w.println(r.getDecompiledFunction().getC());
            else w.println("FAILED: "+r.getErrorMessage());
            w.println();
        }
        w.close(); di.dispose();
    }
}
