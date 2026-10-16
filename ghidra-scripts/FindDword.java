import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.MemoryBlock;
import java.io.*;
public class FindDword extends GhidraScript {
    @Override protected void run() throws Exception {
        PrintWriter w=new PrintWriter(new FileWriter(getScriptArgs()[0]));
        long t=Long.decode(getScriptArgs()[1]).longValue();
        byte[] pat={(byte)(t&0xff),(byte)((t>>8)&0xff),(byte)((t>>16)&0xff),(byte)((t>>24)&0xff)};
        int n=0;
        for(MemoryBlock b: currentProgram.getMemory().getBlocks()){
            try{
                long size=b.getSize();
                if(size<=0||size>8*1024*1024) continue;
                byte[] data=new byte[(int)size];
                b.getBytes(b.getStart(), data);
                for(int i=0;i+4<=data.length;i++){
                    if(data[i]==pat[0]&&data[i+1]==pat[1]&&data[i+2]==pat[2]&&data[i+3]==pat[3]){
                        Address hit=b.getStart().add(i);
                        Function f=getFunctionContaining(hit);
                        w.println(hit+" block="+b.getName()+" fn="+(f==null?"(none)":f.getName()+"@"+f.getEntryPoint()));
                        n++;
                    }
                }
            }catch(Exception e){ w.println("block "+b.getName()+" err "+e); }
        }
        w.println("total "+n);
        w.close();
    }
}
