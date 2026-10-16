import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import java.io.*;
/** Search CODE blocks for the two 16-bit halves of a constant appearing within a few bytes -
 *  i.e. Blackfin X-format LdImmToReg materialisation. Report the containing function. */
public class FindXImm extends GhidraScript {
    @Override protected void run() throws Exception {
        PrintWriter w=new PrintWriter(new FileWriter(getScriptArgs()[0]));
        long t=Long.decode(getScriptArgs()[1]).longValue();
        int lo=(int)(t&0xffff), hi=(int)((t>>16)&0xffff);
        w.println(String.format("searching X-format constant %#x (lo=%#x hi=%#x)", t, lo, hi));
        Memory mem=currentProgram.getMemory();
        FunctionManager fm=currentProgram.getFunctionManager();
        Listing L=currentProgram.getListing();
        for(MemoryBlock b: mem.getBlocks()){
            if(!b.isInitialized()) continue;
            if(b.getSize()>8_000_000) continue;
            byte[] buf=new byte[(int)b.getSize()];
            mem.getBytes(b.getStart(),buf);
            for(int i=0;i+4<=buf.length-16;i++){
                int v1=(buf[i]&0xff)|((buf[i+1]&0xff)<<8);
                if(v1!=hi) continue;
                for(int j=i+2;j<i+16 && j+2<=buf.length;j++){
                    int v2=(buf[j]&0xff)|((buf[j+1]&0xff)<<8);
                    if(v2==lo){
                        Address a=b.getStart().add(i);
                        Instruction ins=L.getInstructionAt(a);
                        Function f=fm.getFunctionContaining(a);
                        w.println(String.format("  %s (insn=%s) in %s", a, ins==null?"none":ins.toString(),
                            f==null?"(none)":f.getName()+"@"+f.getEntryPoint()));
                        break;
                    }
                }
            }
        }
        w.close();
    }
}
