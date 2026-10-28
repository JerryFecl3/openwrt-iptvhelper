const fs=require('fs'),assert=require('assert');
const source=fs.readFileSync('openwrt-iptv/files/www/luci-static/resources/view/iptvhelper/main.js','utf8');
class Element {
 constructor(tag,attrs={},children=[]){this.tag=tag;this.attrs=attrs||{};this.children=[];for(const c of Array.isArray(children)?children:[children])if(c!=null)this.appendChild(c);}
 appendChild(c){this.children.push(c);return c;}
 removeChild(c){this.children.splice(this.children.indexOf(c),1);}
 get firstChild(){return this.children[0];}
 setAttribute(k,v){this.attrs[k]=v;}
 querySelectorAll(){return [];}
 get text(){return this.children.map(c=>c instanceof Element?c.text:String(c)).join('');}
}
const E=(...args)=>new Element(...args);
function all(e){return e instanceof Element?[e,...e.children.flatMap(all)]:[];}
(async()=>{
for(const state of ['ready','disabled','network_unavailable']){
for(const count of [0,1,3,4]){
 const d={readiness:state,service_enabled:state!=='disabled',network:{},platform:{entry:'http://example.test:8082/entry',portal:'http://192.0.2.1:33200/EPG/',auth:{status:'authenticated'},verification:{status:'authenticated'}},collection:{status:state==='ready'?'collected':'network_unavailable',live:{count:150},epg:{count:38000}},services:{},last:{phase:'network_unavailable'}};
 d.services={items:Object.fromEntries(['m3u','epg','relay','player'].map((k,i)=>[k,{ok:i<count}]))};
 const form={Map:class{section(){return {tab(){},taboption(){return {}}}}render(){return Promise.resolve(E('div'))}}};
 const ui={createHandlerFn:(s,f)=>f,tabs:{initTabGroup(){}},addNotification(){}};
 const view=new Function('view','form','rpc','poll','ui','uci','validation','E','_','L','window',source)({extend:x=>x},form,{declare:()=>()=>Promise.resolve(d)},{add(){}},ui,{}, {},E,x=>x,{resource:()=>''},{location:{hostname:'localhost'}});
 const root=await view.render([]),nodes=all(root),platform=nodes.find(n=>n.attrs.id==='iptvhelper-platform'),overview=nodes.find(n=>n.attrs.id==='iptvhelper-overview');
 const badges=all(platform).filter(n=>(n.attrs.class||'').includes('ip-badge'));
 assert.equal(badges.length,2);
 for(const badge of badges){assert(badge.attrs.class.includes(state==='ready'?'ip-good':'ip-warn'));assert(badge.text.includes(state==='disabled'?'已停用':state==='network_unavailable'?'网络未就绪':'成功'));}
 assert.equal(overview.text.includes('192.0.2.1:33200'),state==='ready');
 if(state==='network_unavailable')assert(overview.text.includes('网络未就绪')&&!overview.text.includes('已采集'));
 assert(overview.text.includes('150个频道、38000条节目'));
 const media=nodes.filter(n=>n.tag==='section'&&n.children[0].text.startsWith('媒体服务'));
 assert.equal(media.length,2);
 for(const card of media){const badge=all(card.children[0]).find(n=>(n.attrs.class||'').includes('ip-badge'));assert.equal(badge.text,state==='disabled'?'已停用':count===4?'服务中':count?'部分可用':'服务不可用');}
}
console.log(state+': actual LuCI render and four media states passed');
}
})().catch(e=>{console.error(e);process.exit(1)});
