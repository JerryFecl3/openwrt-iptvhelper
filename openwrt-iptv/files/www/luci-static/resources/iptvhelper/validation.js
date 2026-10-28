'use strict';
'require baseclass';
function field(key,value) {
 value=String(value==null?'':value);
 var ranges={past_days:[0,7],future_days:[0,7]};
 if(ranges[key])return /^[0-9]+$/.test(value)&&Number(value)>=ranges[key][0]&&Number(value)<=ranges[key][1]?true:'请输入 '+ranges[key][0]+'–'+ranges[key][1]+' 范围内的整数';
 if(key==='interface')return /^[A-Za-z0-9_]+$/.test(value)?true:'接口名称只能包含字母、数字和下划线';
 if(key==='user_id')return /^[!-~]{1,128}$/.test(value)&&!value.includes('$')?true:'账号必须为不含空格和 $ 的 ASCII 字符，最多 128 字符';
 if(key==='password')return /^[0-9]{6}$/.test(value)?true:'业务密码必须为 6 位数字';
 if(key==='mac')return !value||/^(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$/.test(value)?true:'请输入完整的机顶盒 MAC 地址';
 if(key==='stb_id')return !value||(/^[!-~]+$/.test(value)&&!value.includes('$'))?true:'机顶盒 ID 须为不含空格、控制字符和 $ 的 ASCII 字符';
 if(key==='entry_url') {
  try {
   if(!value||/\s/.test(value)||!/^https?:\/\//.test(value))return '请输入完整的 HTTP(S) 地址，不允许空格';
   var u=new URL(value);
   if(key==='entry_url'&&u.protocol!=='http:')return '当前平台适配器仅支持 HTTP';
   if(!u.hostname||u.username||u.password||u.search||u.hash||u.port==='0')return '地址不能包含账号、查询参数或片段，端口必须为 1–65535';
   return true;
  } catch(e){return '地址或端口格式无效';}
 }
 return true;
}
return baseclass.extend({field:field});
