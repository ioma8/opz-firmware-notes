import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import java.io.*;
public class RangeStr extends GhidraScript {
    @Override protected void run() throws Exception {
        PrintWriter w=new PrintWriter(new FileWriter(getScriptArgs()[0]));
        Memory m=currentProgram.getMemory();
        long lo=Long.decode(getScriptArgs()[1]).longValue();
        long hi=Long.decode(getScriptArgs()[2]).longValue();
        StringBuilder cur=null; long start=0;
        for(long a=lo;a<hi;a++){
            byte b;
            try{ b=m.getByte(toAddr(a)); }catch(Exception e){ break; }
            if(b>=0x20&&b<0x7f){
                if(cur==null){cur=new StringBuilder(); start=a;}
                cur.append((char)b);
            } else {
                if(cur!=null && cur.length()>=1){ w.println(String.format("%08x %s", start, cur.toString())); }
                cur=null;
            }
        }
        if(cur!=null) w.println(String.format("%08x %s", start, cur.toString()));
        w.close();
    }
}
