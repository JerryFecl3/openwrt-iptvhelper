'use strict';
'require view';
'require form';
'require rpc';
'require poll';
'require ui';
'require uci';
'require iptvhelper.validation as validation';
var getStatus=rpc.declare({object:'iptvhelper',method:'status',expect:{}});
var enableService=rpc.declare({object:'iptvhelper',method:'enable'}),disableService=rpc.declare({object:'iptvhelper',method:'disable'});
var refresh=rpc.declare({object:'iptvhelper',method:'update',expect:{}});
function txt(v){return v==null||v===''?'未知':String(v);}
function date(v){return v?String(v):'未知';}
function hostport(v){try{var u=new URL(v);return u.hostname+':'+(u.port||(u.protocol==='https:'?'443':'80'));}catch(e){return '—';}}
function businessRows(endpoints){
 var tree=[['认证入口','认证入口'],['EPG 门户','├─ 平台门户'],['回看入口','│  ├─ 回看入口'],['回看频道目录','│  │  └─ 回看频道目录'],['节目单查询','│  └─ 节目单查询'],['频道列表','└─ 频道列表']];
 return tree.map(function(item){var r=endpoints.find(function(e){return e.name===item[0]||(item[0]==='EPG 门户'&&e.name==='平台门户');})||{};return [E('span',{'class':'ip-tree-label'},item[1]),r.source||'—',r.url||'尚未发现'];});
}
function replace(el,nodes){while(el.firstChild)el.removeChild(el.firstChild);nodes.forEach(function(n){el.appendChild(n);});}
function badge(label,kind){return E('span',{'class':'ip-badge '+(kind||'')},label);}
function pairs(rows){return E('dl',{},rows.reduce(function(a,r){return a.concat([E('dt',{},r[0]),E('dd',{},r[1]&&typeof r[1]==='object'?r[1]:txt(r[1]))]);},[]));}
function panel(title,nodes,tag){return E('section',{'class':'ip-panel'},[E('div',{'class':'ip-heading'},[E('h3',{},title),tag||E('span')])].concat(nodes));}
function table(head,rows){return E('div',{'class':'ip-table'},[E('table',{'class':'table'},[E('thead',{},[E('tr',{},head.map(function(x){return E('th',{},x);}))]),E('tbody',{},rows.map(function(r){return E('tr',{},r.map(function(x){return E('td',{},x&&typeof x==='object'?x:txt(x));}));}))])]);}
function link(path,label){return E('a',{href:path,target:'_blank',rel:'noopener'},label);}
return view.extend({
 load:function(){return Promise.all([uci.load('iptvhelper'),getStatus()]);},
 render:function(loaded){
  var self=this,m=new form.Map('iptvhelper');
  var s=m.section(form.NamedSection,'main','service');s.anonymous=true;
  s.tab('network',_('网络'));s.tab('platform',_('平台'));s.tab('publish',_('媒体采集'));s.tab('service',_('媒体服务rtp2httpd'));
  var o=s.taboption('publish',form.Flag,'enabled',_('启用自动更新'),_('按每日采集时间自动执行；关闭后仍可手动更新，媒体转发继续运行。'));o.rmempty=false;
  o=s.taboption('network',form.Value,'interface',_('IPTV 逻辑接口'));o.placeholder='iptv';o.rmempty=true;o.datatype='uciname';o.validate=function(id,v){return !v||validation.field('interface',v);};
  o.description=_('该接口的 IP、MAC、主机名等信息将用于平台认证，并作为 rtp2httpd 的上游接口。');
  o=s.taboption('network',form.Value,'route_table',_('IPTV 专用路由表号'));o.placeholder='42420';o.rmempty=true;o.validate=function(id,v){return !v||/^[0-9]+$/.test(v)&&Number(v)>0&&Number(v)<=4294967295&&[253,254,255].indexOf(Number(v))<0?true:'请输入非系统保留的有效路由表号';};
  o=s.taboption('platform',form.Value,'entry_url',_('平台地址'));o.rmempty=false;o.validate=function(id,v){return validation.field('entry_url',v);};
  o=s.taboption('network',form.Value,'dns_override',_('IPTV DNS 覆盖'));o.datatype='ip4addr';o.rmempty=true;o.placeholder='自动获取';
  o.description=_('留空读取接口 DNS，包括 DHCP 下发但未被系统采纳的地址。填写后仅覆盖本插件的 IPTV 解析，不修改系统 DNS 或 rtp2httpd。');
  o=s.taboption('publish',form.DynamicList,'collect_times',_('每日采集时间'));o.rmempty=true;o.optional=true;o.placeholder='08:00';o.description=_('按系统时区，每两分钟检查一次。错过的时段合并执行，失败仅在本次任务内重试。');o.validate=function(id,v){if(v==null||v==='')return true;var a=Array.isArray(v)?v:[v];return a.length&&a.every(function(t){return /^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/.test(t);})?true:_('请输入 HH:MM 格式的时间');};
  [['past_days','过去天数',0,7],['future_days','未来天数',0,7]].forEach(function(x){var f=s.taboption('publish',form.Value,x[0],_(x[1]));f.datatype='and(uinteger,range('+x[2]+','+x[3]+'))';f.rmempty=true;f.placeholder=x[0]==='past_days'?'7':'3';f.description=_(x[0]==='past_days'?'设置采集过去多少天的节目单，留空使用 7 天。':'设置采集未来多少天的节目单，留空使用 3 天。');f.validate=function(id,v){return !v||validation.field(x[0],v);};});
  [['user_id','业务账号'],['password','业务密码']].forEach(function(x){var f=s.taboption('platform',form.Value,x[0],_(x[1]));f.rmempty=false;f.validate=function(id,v){return validation.field(x[0],v);};if(x[0]=='password')f.password=true;});
  var listenIP=s.taboption('service',form.Value,'relay_listen',_('监听地址'));listenIP.description=_('配置助手专属 rtp2httpd 实例；不修改官方实例。');listenIP.datatype='ip4addr';listenIP.placeholder='0.0.0.0';listenIP.rmempty=true;
  var listenPort=s.taboption('service',form.Value,'relay_port',_('监听端口'));listenPort.description=_('助手专属实例默认使用 5141，端口占用时不会停止其他实例。');listenPort.datatype='port';listenPort.placeholder='5141';listenPort.rmempty=true;listenPort.validate=function(id,v){return !v||/^\d+$/.test(v)&&Number(v)>0&&Number(v)<=65535?true:'端口必须为 1–65535';};
  var names={overview:'状态总览',network:'网络状态',platform:'平台状态',publish:'媒体状态',settings:'配置'},panels={};
  var tabPanes=Object.keys(names).map(function(k){return panels[k]=E('div',{id:'iptvhelper-'+k,'data-tab':k,'data-tab-title':names[k]});});
  var refreshButtons=[],requesting=false,masterEnabled=true;
  var master=E('button',{type:'button','class':'cbi-button',click:ui.createHandlerFn(self,function(){master.disabled=true;return (masterEnabled?disableService():enableService()).then(function(r){if(r.error)throw Error(r.error);return update();}).catch(function(){ui.addNotification(null,E('p',{},'切换失败，请检查服务状态。'));}).finally(function(){master.disabled=false;});})},'已启用');
  function updateButton(){var button=E('button',{type:'button','class':'cbi-button cbi-button-action',click:ui.createHandlerFn(self,function(){
   requesting=true;refreshButtons.forEach(function(b){b.disabled=true;b.textContent='更新中…';});
   return refresh().then(function(r){if(r.accepted===false)ui.addNotification(null,E('p',{},'已有任务运行，本次不重复启动。'),'info');return update();}).catch(function(){ui.addNotification(null,E('p',{},'更新请求失败，请检查状态服务。'),'error');}).finally(function(){requesting=false;update();});
  })},'更新');refreshButtons.push(button);return button;}
  var overviewUpdate=updateButton(),mediaUpdate=updateButton();

  var error=E('div',{'class':'ip-error',hidden:true,role:'alert'});
  function draw(d){
   masterEnabled=d.service_enabled!==false;master.textContent=masterEnabled?'已启用':'已停用';master.setAttribute('aria-pressed',String(masterEnabled));
   var n=d.network||{},p=d.platform||{},a=d.last||{},v=d.success||{},g=d.progress||{},sc=d.schedule||{},pub=d.publication||{},running=a.phase==='running';
   var co=d.collection||{};
   var autoUpdate=d.enabled?(sc.collect_times||[]).join('、'):'未开启';
   var serviceCount=['m3u','epg','relay','player'].filter(function(k){return (((d.services||{}).items||{})[k]||{}).ok;}).length;
   var serviceLabel=!masterEnabled?'已停用':serviceCount===4?'服务中':serviceCount>0?'部分可用':'服务不可用';
   var serviceKind=masterEnabled&&serviceCount===4?'ip-good':'ip-warn';
   function serviceState(k){return !masterEnabled?'已停用':(((d.services||{}).items||{})[k]||{}).ok?'服务中':'服务不可用';}
   function collected(k){var x=co[k]||{};return x.count==null?'—':x.count+' · '+(x.changed?date(x.changed):'—');}
   var phase={running:'采集中',ready:'已完成',degraded:'部分失败',failed:'更新失败',interrupted:'已中断',needs_configuration:'等待配置',disabled:'已停用',network_unavailable:'网络未就绪'}[a.phase]||'尚未运行';
   var auth=p.auth||{},verification=p.verification||{},authLabel={authenticated:'认证成功',failed:'认证失败',unauthenticated:'未认证'}[auth.status]||'未认证',verifyLabel={authenticated:'验证成功',failed:'验证失败',unreachable:'平台不可达',unauthenticated:'未验证'}[verification.status]||'未验证';
   if(d.readiness==='disabled')authLabel=verifyLabel='已停用';
   else if(d.readiness==='network_unavailable')authLabel=verifyLabel='网络未就绪';
   var dnsSource={manual:'自定义',interface:'接口配置',dhcp_inactive:'DHCP',unavailable:'无可用 DNS'}[n.dns_source]||'未知';
   refreshButtons.forEach(function(b){b.disabled=!!(!masterEnabled||running||d.pending||requesting);b.textContent=running||requesting?'更新中…':'更新';});
   var progress=running&&g.total?E('div',{},[E('div',{'class':'ip-heading'},[E('span',{},'当前日期 · '+txt(g.date)),E('span',{},txt(g.done)+' / '+txt(g.total)+' 频道')]),E('div',{'class':'ip-track',role:'progressbar','aria-label':'当前日期频道采集进度','aria-valuenow':g.done||0,'aria-valuemin':0,'aria-valuemax':g.total},[E('span',{style:'width:'+Math.max(0,Math.min(100,100*(g.done||0)/g.total))+'%'})])]):E('p',{'class':'ip-muted'},running?'正在认证或发现业务入口…':'下次计划：'+(d.enabled?date(sc.next_run):'自动更新已关闭'));
   function endpoint(path){return path;}
   function updated(button){return E('span',{'class':'ip-actions'},[E('span',{},co.updated?date(co.updated):'—'),button]);}
   function mediaURL(path){return 'http://'+window.location.hostname+':'+(d.media_port||5141)+path;}
   function serviceLink(key,url){return (((d.services||{}).items||{})[key]||{}).ok?E('a',{href:url,target:'_blank',rel:'noopener'},url):E('span',{},'-');}
   replace(panels.overview,[E('div',{'class':'ip-grid'},[
    panel('专网接入',[pairs([['接口 / 设备',txt(n.interface)+' / '+txt(n.device)],['IP 地址',n.address?txt(n.address)+(n.mask!=null?'/'+n.mask:''):'未获得'],['网关',n.gateway],['DNS',(n.dns||[]).length?n.dns.join('、')+'（'+dnsSource+'）':'未获得，请配置覆盖']])],badge(n.up?'已连接':'未连接',n.up?'ip-good':'ip-warn')),
    panel('平台接入',[pairs([['最后认证',auth.checked?date(auth.checked):'—'],['平台地址',hostport(p.entry)],['最近会话',verification.checked?date(verification.checked):'—'],['平台节点',d.readiness==='ready'&&verification.status==='authenticated'?hostport(p.portal):'未能成功获取']])],badge(authLabel,d.readiness==='ready'&&auth.status==='authenticated'?'ip-good':'ip-warn')),
    panel('媒体采集',[pairs([['最近更新',updated(overviewUpdate)],['下次更新',d.enabled?(running?'本次完成后安排':date(sc.next_run)):'—'],['自动更新',autoUpdate],['媒体信息',txt((co.live||{}).count)+'个频道、'+txt((co.epg||{}).count)+'条节目']])],badge({network_unavailable:'网络未就绪',empty:'未采集',collected:'已采集',partial:'部分失败',failed:'采集失败'}[co.status]||'未采集',co.status==='collected'?'ip-good':'ip-warn')),
    panel('媒体服务',[(d.relay||{}).error?E('p',{'class':'ip-warn'},'专属转发：'+d.relay.error):E('span'),pairs([['M3U 播放列表',serviceLink('m3u',mediaURL('/playlist.m3u'))],['EPG 节目单',serviceLink('epg',mediaURL('/epg.xml'))],['流媒体转发',serviceLink('relay',mediaURL('/status'))],['网页播放器',serviceLink('player',mediaURL('/player'))]])],badge(serviceLabel,serviceKind))])]);
   replace(panels.network,[panel('专网接入',[pairs([['接口 / 设备',txt(n.interface)+' / '+txt(n.device)],['IP 地址',n.address?txt(n.address)+'/'+txt(n.mask):'未获得'],['网关',n.gateway],['DNS',(n.dns||[]).join('、')+'（'+dnsSource+'）'],['MAC 地址',n.mac],['主机名',n.hostname]])],badge(n.up?'已连接':'未连接',n.up?'ip-good':'ip-warn')),panel('专用路由',[pairs([['路由表号',(d.policy||{}).table],['路由条目',E('div',{},((d.policy||{}).routes||[]).length?(d.policy.routes.map(function(route){return E('div',{style:'overflow-wrap:anywhere'},String(route).trim());})):[E('div',{},'暂无路由')])]])])]);
   replace(panels.platform,[panel('平台认证',[pairs([['平台地址',p.entry],['业务账号',p.account],['业务密码',p.password_configured?'••••••':'未配置'],['最近登录',auth.checked?date(auth.checked):'—']])],badge(authLabel,d.readiness==='ready'&&auth.status==='authenticated'?'ip-good':'ip-warn')),
    panel('业务验证',[pairs([['最近会话',verification.checked?date(verification.checked):'—']]),verification.error?E('p',{'class':'ip-muted'},'本次验证未成功（'+verification.error+'）'):E('span'),verification.status!=='authenticated'&&verification.has_snapshot?E('p',{'class':'ip-muted'},'以下保留上次成功获取的业务入口。'):E('span'),table(['业务入口','来源','地址（已去除令牌）'],businessRows(p.endpoints||[])),E('p',{'class':'ip-muted'},'区分认证返回、页面引用与地域适配器。状态接口不返回 Cookie、密码或带查询参数的地址。')],badge(verifyLabel,d.readiness==='ready'&&verification.status==='authenticated'?'ip-good':'ip-warn'))]);
   var expanded={};panels.publish.querySelectorAll('details[data-detail]').forEach(function(el){expanded[el.getAttribute('data-detail')]=el.open;});
   function detail(key,title,children){var el=E('details',{'data-detail':key,'class':'ip-detail'},[E('summary',{},title)].concat(children));el.open=!!expanded[key];return el;}
   var collectionRows=[['live','直播列表'],['catchup','回看列表'],['epg','节目单']].map(function(r){var x=co[r[0]]||{};return[r[1],x.count==null?'—':String(x.count),x.changed?date(x.changed):'—'];});
   replace(panels.publish,[
    panel('媒体采集',[
     pairs([['最近更新',updated(mediaUpdate)],['下次更新',d.enabled?(running?'本次完成后安排':date(sc.next_run)):'—'],['自动更新',autoUpdate],['媒体信息',txt((co.live||{}).count)+'个频道、'+txt((co.epg||{}).count)+'条节目']]),
     running?progress:E('span'),
     (co.status==='failed'||co.status==='partial')?E('p',{'class':'ip-warn'},'本次有采集或发布步骤未完成；可用内容继续提供，失败任务将自动重试。'):E('span'),
     table(['内容','数量','末次变化'],collectionRows),
     detail('coverage','节目单覆盖',[table(['日期','有节目','空节目单','失败 / 旧缓存'],(pub.coverage||[]).map(function(r){return[r.date,r.with_programmes,r.empty,txt(r.failed)+' / '+txt(r.stale)];})),E('p',{'class':'ip-muted'},'按频道统计；空节目单不等于请求失败。正在采集的日期不计入已发布覆盖。')]),
     detail('task','最近任务详情',[pairs([['状态',phase],['开始',date(a.started)],['结束',running?'进行中':date(a.finished)],['最近成功请求 / 缓存',txt(v.requests)+' / '+txt(v.cached)],['最近成功失败 / 旧缓存',(v.errors||[]).length+' / '+(v.stale||[]).length]]),a.error?E('p',{'class':'ip-warn'},'本轮错误：'+a.error):E('span')])
    ],badge(running?'采集中':({network_unavailable:'网络未就绪',empty:'未采集',collected:'已采集',partial:'部分失败',failed:'采集失败'}[co.status]||'未采集'),co.status==='collected'&&!running?'ip-good':'ip-warn')),
    panel('媒体服务',[
     (d.relay||{}).error?E('p',{'class':'ip-warn'},'专属转发：'+d.relay.error):E('span'),
     table(['服务','状态','访问地址'],[
      ['M3U 播放列表',serviceState('m3u'),link(mediaURL('/playlist.m3u'),mediaURL('/playlist.m3u'))],
      ['EPG 节目单',serviceState('epg'),link(mediaURL('/epg.xml'),mediaURL('/epg.xml'))],
      ['流媒体转发',serviceState('relay'),link(mediaURL('/status'),mediaURL('/status'))],
      ['网页播放器',serviceState('player'),link(mediaURL('/player'),mediaURL('/player'))]
     ])
    ],badge(serviceLabel,serviceKind))
   ]);
  }
  function update(){return getStatus().then(function(d){draw(d);error.hidden=true;}).catch(function(){error.hidden=false;replace(error,[E('span',{},'状态读取失败；下方为上次快照，不能视为当前状态。请检查 rpcd 与插件。')]);});}
  return m.render().then(function(node){
   panels.settings.appendChild(node);
   return update().then(function(){
    var root=E('div',{'class':'iptvhelper'},[E('link',{rel:'stylesheet',href:L.resource('iptvhelper/dashboard.css')+'?v=overview-spacing-20261027'}),E('div',{'class':'ip-heading'},[E('div',{style:'display:flex;align-items:center;gap:12px'},[E('h2',{},'IPTV 助手'),master])]),error,E('div',{},tabPanes)]);
    ui.tabs.initTabGroup(tabPanes);poll.add(update,15);return root;
   });
  });
 }
});
