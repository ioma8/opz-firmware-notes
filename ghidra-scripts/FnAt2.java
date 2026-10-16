import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
import java.io.*;
public class FnAt2 extends GhidraScript {
    @Override protected void run() throws Exception {
        PrintWriter w=new PrintWriter(new FileWriter(getScriptArgs()[0]));
        for(int i=1;i<getScriptArgs().length;i++){
            Address a=toAddr(getScriptArgs()[i]);
            Function f=getFunctionContaining(a);
            w.println(a+" -> "+(f==null?"(none)":f.getName()+" entry="+f.getEntryPoint()+" size="+f.getBody().getNumAddresses()));
        }
        w.close();
    }
}
