import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../../static/js/dashboard-charts.js',import.meta.url),'utf8');
const context=vm.createContext({Intl,matchMedia:()=>({matches:true})});vm.runInContext(source,context);
const charts=context.FinoraDashboardCharts;
const theme={text:'#222',muted:'#777',font:'Arial'};
test('compact axes handle exact units, negative profit and zero',()=>{
 for(const [n,s] of [[0,'0'],[500,'500'],[1500,'1.5 ألف'],[1500000,'1.5 مليون'],[2e9,'2 مليار'],[-1500000,'-1.5 مليون'],[NaN,'0']])assert.equal(charts.compact(n),s);
});
test('financial tooltips retain full value and currency',()=>{
 const options=charts.moneyOptions(theme,n=>Number(n).toLocaleString('en-US'));
 assert.equal(options.plugins.tooltip.callbacks.label({dataset:{label:'الربح'},parsed:{y:-1234567}}),'الربح: -1,234,567 د.ع');
 assert.equal(options.animation,false);
});
test('status tooltips show counts and percentages without currency',()=>{
 const label=charts.statusTooltip({label:'تم الطلب',parsed:25,dataset:{data:[25,75]}},String);
 assert.equal(label,'تم الطلب: 25 (25%)');assert.ok(!label.includes('د.ع'));
 assert.equal(charts.statusTooltip({label:'تم الطلب',parsed:0,dataset:{data:[0,0]}},String),'تم الطلب: 0');
});
test('resizing changes label density, preserving source values',()=>{
 const options=charts.moneyOptions(theme,String),data=[1,-2,30000000],chart={options,data};
 options.onResize(chart,{width:280});assert.equal(options.scales.x.ticks.maxTicksLimit,4);
 options.onResize(chart,{width:900});assert.equal(options.scales.x.ticks.maxTicksLimit,12);
 assert.deepEqual(data,[1,-2,30000000]);
});
