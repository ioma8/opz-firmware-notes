import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.Memory;
import java.io.*;
public class HexRange extends GhidraScript {
    @Override protected void run() throws Exception {
        PrintWriter w=new PrintWriter(new FileWriter(getScriptArgs()[0]));
        Address a=toAddr(getScriptArgs()[1]); int len=Integer.decode(getScriptArgs()[2]);
        Memory mem=currentProgram.getMemory();
        byte[] buf=new byte[len]; mem.getBytes(a,buf);
        for(int i=0;i<len;i+=16){
            StringBuilder h=new StringBuilder(), s=new StringBuilder();
            for(int j=0;j<16&&i+j<len;j++){int v=buf[i+j]&0xff; h.append(String.format("%02x ",v)); s.append(v>=32&&v<127?(char)v:'.');}
            w.println(String.format("%s  %-48s %s", a.add(i), h, s));
        }
        w.close();
    }
}
