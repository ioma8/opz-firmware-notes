/* Stage 1: wordlist x mangling rules -> {raw16, raw32, md5, sha256} key forms,
   checked against the hardware-leaked plaintext block in one AES block.
   Check: E_k(T) == C300,  T = "firmware_bin_onl" XOR IV. */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <pthread.h>
#include <time.h>
#include <openssl/md5.h>
#include <openssl/sha.h>
#include <openssl/aes.h>

#define MAXOPS 8
#define MAXLEN 120
typedef struct { unsigned char op,a,b; int n; } Op;
typedef struct { Op o[MAXOPS]; int n; int ok; } Rule;
static Rule rules[512]; static int nrules=0, nskipped=0;

static unsigned char IV[16], T[16], C300[16], C3F0[16], C400[16];
static const unsigned char ZIP[19]={0x50,0x4b,0x03,0x04,0x14,0x00,0xc0,0x1e,0x04,0x00,0x00,0x00,0x49,0xfb,0xbe,0x94,0x19,0x5b,0x00};
static const char *WANT="firmware_bin_onl";

static char rule_text[512][64];
static char *WBUF; static size_t *WOFF; static size_t NW=0;
static volatile int found=0; static char foundinfo[512];
static unsigned long long g_cands=0; static pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;

static int parse_rule(const char*s, Rule*r){
  r->n=0; r->ok=1;
  char *dup=strdup(s), *tok, *save=NULL;
  for(tok=strtok_r(dup," ",&save); tok; tok=strtok_r(NULL," ",&save)){
    if(!*tok) continue;
    if(r->n>=MAXOPS){ r->ok=0; break; }
    Op op; memset(&op,0,sizeof op); op.op=(unsigned char)tok[0];
    const char*arg=tok+1; int alen=(int)strlen(arg);
    switch(op.op){
      case ':': case 'l': case 'u': case 'c': case 'C': case 't': case 'r': case 'd':
      case 'f': case 'q': case 'k': case 'K': case '{': case '}': case '[': case ']':
        break;
      case '$': case '^': case 's': case 'o': case 'i': case '@':
        if(alen<1){ r->ok=0; break; }
        op.a=(unsigned char)arg[0];
        if(op.op=='s'||op.op=='o'||op.op=='i'){ if(alen<2 && op.op!='s'){r->ok=0;break;} }
        if(op.op=='s'){ if(alen<2){r->ok=0;break;} op.b=(unsigned char)arg[1]; }
        if(op.op=='o'||op.op=='i'){
          op.n=atoi(arg); const char*p=arg; while(*p>='0'&&*p<='9')p++; if(!*p){r->ok=0;break;} op.b=(unsigned char)*p;
        }
        break;
      case 'T': case 'D': case 'O': case '\'': case 'p': case 'z': case 'Z': case '+': case '-':
        op.n=atoi(arg); break;
      case 'x': { const char*p=arg; op.n=atoi(p); while(*p>='0'&&*p<='9')p++; op.b=(unsigned char)(*p?atoi(p):0); break; }
      default: r->ok=0; break;   /* unsupported (e.g. Y=memory-match) */
    }
    if(!r->ok) break;
    r->o[r->n++]=op;
  }
  free(dup);
  return r->ok && r->n>0;
}

static int apply(const Rule*r,const unsigned char*in,int inlen,unsigned char*out){
  unsigned char b[MAXLEN]; int len=inlen;
  if(len>MAXLEN-8) len=MAXLEN-8;
  memcpy(b,in,len);
  for(int i=0;i<r->n;i++){
    Op o=r->o[i];
    switch(o.op){
      case ':': break;
      case 'l': for(int j=0;j<len;j++) if(b[j]>='A'&&b[j]<='Z') b[j]+=32; break;
      case 'u': for(int j=0;j<len;j++) if(b[j]>='a'&&b[j]<='z') b[j]-=32; break;
      case 'c': for(int j=0;j<len;j++){ if(j==0){ if(b[j]>='a'&&b[j]<='z') b[j]-=32; } else if(b[j]>='A'&&b[j]<='Z') b[j]+=32; } break;
      case 'C': for(int j=0;j<len;j++){ if(j==0){ if(b[j]>='A'&&b[j]<='Z') b[j]+=32; } else if(b[j]>='a'&&b[j]<='z') b[j]-=32; } break;
      case 't': for(int j=0;j<len;j++){ if(b[j]>='a'&&b[j]<='z') b[j]-=32; else if(b[j]>='A'&&b[j]<='Z') b[j]+=32; } break;
      case 'T': if(o.n<len){ unsigned char c=b[o.n]; if(c>='a'&&c<='z')c-=32; else if(c>='A'&&c<='Z')c+=32; b[o.n]=c; } break;
      case 'r': for(int j=0;j<len/2;j++){ unsigned char t=b[j]; b[j]=b[len-1-j]; b[len-1-j]=t; } break;
      case 'd': if(len*2<MAXLEN){ memcpy(b+len,b,len); len*=2; } break;
      case 'f': if(len*2<MAXLEN){ for(int j=0;j<len;j++) b[len+j]=b[len-1-j]; len*=2; } break;
      case '{': if(len>1){ unsigned char c=b[0]; memmove(b,b+1,len-1); b[len-1]=c; } break;
      case '}': if(len>1){ unsigned char c=b[len-1]; memmove(b+1,b,len-1); b[0]=c; } break;
      case '$': if(len<MAXLEN-1) b[len++]=o.a; break;
      case '^': if(len<MAXLEN-1){ memmove(b+1,b,len); b[0]=o.a; len++; } break;
      case '[': if(len>0){ memmove(b,b+1,len-1); len--; } break;
      case ']': if(len>0) len--; break;
      case 'D': case 'O': if(o.n>=0&&o.n<len){ memmove(b+o.n,b+o.n+1,len-o.n-1); len--; } break;
      case '\'': if(o.n<len) len=o.n; break;
      case 's': for(int j=0;j<len;j++) if(b[j]==o.a) b[j]=o.b; break;
      case '@': { int w=0; for(int j=0;j<len;j++) if(b[j]!=o.a) b[w++]=b[j]; len=w; } break;
      case 'o': if(o.n>=0&&o.n<len) b[o.n]=o.b; break;
      case 'i': if(o.n>=0&&o.n<=len&&len<MAXLEN-1){ memmove(b+o.n+1,b+o.n,len-o.n); b[o.n]=o.b; len++; } break;
      case 'k': if(len>1){ unsigned char t=b[0]; b[0]=b[1]; b[1]=t; } break;
      case 'K': if(len>1){ unsigned char t=b[len-1]; b[len-1]=b[len-2]; b[len-2]=t; } break;
      case 'z': { int c=o.n>0?o.n:1; while(c-->0&&len>0&&len<MAXLEN-1){ memmove(b+1,b,len); b[0]=b[1]; len++; } } break;
      case 'Z': { int c=o.n>0?o.n:1; while(c-->0&&len>0&&len<MAXLEN-1){ b[len]=b[len-1]; len++; } } break;
      case 'q': { unsigned char t[MAXLEN]; int w=0; for(int j=0;j<len&&w<MAXLEN-2;j++){ t[w++]=b[j]; t[w++]=b[j]; } memcpy(b,t,w); len=w; } break;
      case '+': if(o.n>=0&&o.n<len) b[o.n]++; break;
      case '-': if(o.n>=0&&o.n<len) b[o.n]--; break;
      case 'x': { if(o.n>=0&&o.n<len){ int c=o.b?o.b:len-o.n; if(c>len-o.n)c=len-o.n; memmove(b,b+o.n,c); len=c; } } break;
      default: return 0;
    }
  }
  memcpy(out,b,len); return len;
}

static inline int aes_hit(const unsigned char*key,int klen){
  AES_KEY k; unsigned char out[16];
  AES_set_encrypt_key(key,klen*8,&k);
  AES_encrypt(T,out,&k);
  return memcmp(out,C300,16)==0;
}

static void try_candidate(const unsigned char*c,int len,const char*word,const char*rule){
  unsigned char k[32];
  if(len>0){
    memset(k,0,32); memcpy(k,c,len>16?16:len);
    if(aes_hit(k,16)){ pthread_mutex_lock(&lock); if(!found){found=1; snprintf(foundinfo,sizeof foundinfo,"raw16 word=%s rule=[%s] key=",word,rule); for(int i=0;i<16;i++) snprintf(foundinfo+strlen(foundinfo),sizeof(foundinfo)-strlen(foundinfo),"%02x",k[i]);} pthread_mutex_unlock(&lock); }
    memset(k,0,32); memcpy(k,c,len>32?32:len);
    if(aes_hit(k,32)){ pthread_mutex_lock(&lock); if(!found){found=1; snprintf(foundinfo,sizeof foundinfo,"raw32 word=%s rule=[%s] key=",word,rule); for(int i=0;i<32;i++) snprintf(foundinfo+strlen(foundinfo),sizeof(foundinfo)-strlen(foundinfo),"%02x",k[i]);} pthread_mutex_unlock(&lock); }
  }
  unsigned char h[32];
  MD5(c,len,h); if(aes_hit(h,16)){ pthread_mutex_lock(&lock); if(!found){found=1; snprintf(foundinfo,sizeof foundinfo,"md5 word=%s rule=[%s] key=",word,rule); for(int i=0;i<16;i++) snprintf(foundinfo+strlen(foundinfo),sizeof(foundinfo)-strlen(foundinfo),"%02x",h[i]);} pthread_mutex_unlock(&lock); }
  SHA256(c,len,h); if(aes_hit(h,32)){ pthread_mutex_lock(&lock); if(!found){found=1; snprintf(foundinfo,sizeof foundinfo,"sha256 word=%s rule=[%s] key=",word,rule); for(int i=0;i<32;i++) snprintf(foundinfo+strlen(foundinfo),sizeof(foundinfo)-strlen(foundinfo),"%02x",h[i]);} pthread_mutex_unlock(&lock); }
}

static int NT=8; static size_t shard_lo[128], shard_hi[128];
static void* worker(void*arg){
  long tid=(long)arg; unsigned long long local=0;
  unsigned char out[MAXLEN]; int olen;
  for(size_t wi=shard_lo[tid]; wi<shard_hi[tid] && !found; wi++){
    const unsigned char*w=(const unsigned char*)(WBUF+WOFF[wi]); int wl=(int)(WOFF[wi+1]-WOFF[wi]);
    while(wl>0 && (w[wl-1]=='\n'||w[wl-1]=='\r')) wl--;
    if(wl<=0) continue;
    char wbuf[80]; int wc=wl<79?wl:79; memcpy(wbuf,w,wc); wbuf[wc]=0;
    char rbuf[64];
    for(int ri=0;ri<nrules && !found;ri++){
      snprintf(rbuf,sizeof rbuf,"%s",rule_text[ri]);
      olen=apply(&rules[ri],w,wl,out);
      if(olen<=0) continue;
      try_candidate(out,olen,wbuf,rbuf);
      local++;
    }
  }
  pthread_mutex_lock(&lock); g_cands+=local; pthread_mutex_unlock(&lock);
  return NULL;
}

static int load_words(const char*path){
  FILE*f=fopen(path,"rb"); if(!f){ perror("wordlist"); return -1; }
  fseek(f,0,SEEK_END); long sz=ftell(f); fseek(f,0,SEEK_SET);
  WBUF=malloc(sz+2); if(!WBUF){fprintf(stderr,"oom\n");return -1;}
  if(fread(WBUF,1,sz,f)!=(size_t)sz){fprintf(stderr,"read short\n");return -1;}
  fclose(f); WBUF[sz]='\n'; WBUF[sz+1]=0;
  WOFF=malloc(sizeof(size_t)* (size_t)(sz/2+64));
  size_t i=0,n=0; WOFF[n++]=0;
  for(i=0;i<(size_t)sz;i++) if(WBUF[i]=='\n') WOFF[n++]=i+1;
  WOFF[n]= (size_t)sz+1; NW=n;
  return 0;
}

int main(int argc,char**argv){
  const char*env=getenv("OPZ_ZFW");
  const char*zfw=env?env:"/Users/jakubkolcar/projects/customs/opz-firmware-notes/z_firmware_1_2_45.zfw";
  FILE*z=fopen(zfw,"rb"); if(!z){perror("zfw");return 2;}
  unsigned char hdr[0x410]; if(fread(hdr,1,sizeof hdr,z)!=sizeof hdr){fprintf(stderr,"short zfw\n");return 2;} fclose(z);
  memcpy(IV,hdr+0x70,16); memcpy(C300,hdr+0x300,16); memcpy(C3F0,hdr+0x3F0,16); memcpy(C400,hdr+0x400,16);
  for(int i=0;i<16;i++) T[i]=(unsigned char)WANT[i]^IV[i];

  if(argc>3) NT=atoi(argv[3]); if(NT<1)NT=1; if(NT>64)NT=64;

  const char*rulefile = argc>2?argv[2]:"/Users/jakubkolcar/.opz-decode/wordlists/best66.rule";
  FILE*rf=fopen(rulefile,"r"); if(!rf){perror("rules");return 2;}
  char line[512];
  while(fgets(line,sizeof line,rf)){
    char*p=line; while(*p==' '||*p=='\t')p++;
    if(!*p||*p=='\n'||*p=='\r'||*p=='#') continue;
    size_t l=strlen(p); while(l&&(p[l-1]=='\n'||p[l-1]=='\r')) p[--l]=0;
    Rule r; if(parse_rule(p,&r)){ snprintf(rule_text[nrules],sizeof rule_text[0],"%s",p); rules[nrules++]=r; } else nskipped++;
  }
  fclose(rf);
  printf("rules: %d loaded, %d skipped\n", nrules, nskipped);

  if(load_words(argc>1?argv[1]:"/Users/jakubkolcar/.opz-decode/wordlists/rockyou.txt")) return 2;
  printf("words: %zu   threads: %d\n", NW, NT);

  size_t per=NW/NT+1;
  for(int t=0;t<NT;t++){ shard_lo[t]=t*per; shard_hi[t]=(t+1)*per>NW?NW:(t+1)*per; }

  struct timespec a,b; clock_gettime(CLOCK_MONOTONIC,&a);
  pthread_t th[64];
  for(long t=0;t<NT;t++) pthread_create(&th[t],NULL,worker,(void*)t);
  for(long t=0;t<NT;t++) pthread_join(th[t],NULL);
  clock_gettime(CLOCK_MONOTONIC,&b);
  double dt=b.tv_sec-a.tv_sec+(b.tv_nsec-a.tv_nsec)/1e9;

  printf("candidates: %llu in %.1f s  (%.0f/s)\n", g_cands, dt, g_cands/dt);
  if(found) printf("HIT: %s\n", foundinfo); else printf("no hit\n");
  return found?0:1;
}
