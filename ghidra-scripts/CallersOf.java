import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.Reference;
import java.io.*;
public class CallersOf extends GhidraScript {
    @Override protected void run() throws Exception {
        PrintWriter w=new PrintWriter(new FileWriter(getScriptArgs()[0]));
        for(int i=1;i<getScriptArgs().length;i++){
            Address t=toAddr(getScriptArgs()[i]);
            w.println("=== callers of "+t);
            for(Reference r: getReferencesTo(t)){
                Function f=getFunctionContaining(r.getFromAddress());
                w.println("   "+r.getFromAddress()+"  "+(f==null?"(no fn)":f.getName()+"@"+f.getEntryPoint())+"  type="+r.getReferenceType());
            }
        }
        w.close();
    }
}
