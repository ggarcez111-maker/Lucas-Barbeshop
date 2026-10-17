/* Lucas Barbershop — Etapa 4. DEMONSTRAÇÃO LOCAL. Nenhuma reserva é enviada a servidor. */
(function(){
'use strict';
const KEY='lucasbarbershop-demo-v4';
const defaults={version:4,services:[
{id:'corte',name:'Corte masculino',minutes:40,price:null,description:'Corte masculino com acabamento.',image:'corte-finalizado'},
{id:'barba',name:'Barba e bigode',minutes:30,price:null,description:'Barba e bigode.',image:'barba-precisao'},
{id:'combo',name:'Cabelo e barba',minutes:70,price:null,description:'Corte e barba no mesmo horário.',image:'corte-tesoura'}
],barbers:[{id:'barber1',name:'Profissional 1'},{id:'barber2',name:'Profissional 2'},{id:'barber3',name:'Profissional 3'},{id:'barber4',name:'Profissional 4'}],bookings:[],bot:{active:false,mode:'manual',welcome:'Olá! Bem-vindo à Lucas Barbershop. Como podemos ajudar?',fallback:'Para marcar um horário, acesse a agenda no nosso site.'}};
function load(){try{let value=localStorage.getItem(KEY);if(!value)return structuredClone(defaults);let parsed=JSON.parse(value);if(parsed.version!==4||!Array.isArray(parsed.services)||!Array.isArray(parsed.barbers)||!Array.isArray(parsed.bookings))return structuredClone(defaults);return parsed}catch(e){return structuredClone(defaults)}}
function save(db){localStorage.setItem(KEY,JSON.stringify(db));window.dispatchEvent(new CustomEvent('lucas-demo-change'))}
function escape(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function pad(n){return String(n).padStart(2,'0')}
function dateKey(dt){return [dt.getFullYear(),pad(dt.getMonth()+1),pad(dt.getDate())].join('-')}
function fromKey(key){let a=key.split('-').map(Number);return new Date(a[0],a[1]-1,a[2],12)}
function datePlus(dt,days){let x=new Date(dt);x.setDate(x.getDate()+days);return x}
function dateBr(key,opt){return new Intl.DateTimeFormat('pt-BR',opt||{day:'2-digit',month:'long',year:'numeric'}).format(fromKey(key))}
function hoursFor(key){let day=fromKey(key).getDay();return ({0:[8,13],1:[9,20],2:[9,20],3:[9,20],4:[9,21],5:[8,22],6:[8,20]})[day]}
function minutes(s){let a=s.split(':').map(Number);return a[0]*60+a[1]}
function availableSlots(db,date,barberId,serviceId){let service=db.services.find(s=>s.id===serviceId),barber=db.barbers.find(b=>b.id===barberId);if(!service||!barber)return [];let [start,end]=hoursFor(date);let taken=db.bookings.filter(x=>x.date===date&&x.barberId===barberId&&x.status!=='cancelado').map(x=>({start:minutes(x.time),end:minutes(x.time)+(x.duration||40)}));let items=[];for(let m=start*60;m+service.minutes<=end*60;m+=30){if(taken.some(x=>m<x.end&&m+service.minutes>x.start))continue;items.push(pad(Math.floor(m/60))+':'+pad(m%60))}return items}
function addBooking(payload){let db=load();let slots=availableSlots(db,payload.date,payload.barberId,payload.serviceId);if(!slots.includes(payload.time))return {ok:false,message:'Esse horário já não está livre nesta demonstração.'};let service=db.services.find(s=>s.id===payload.serviceId);let item={id:'demo-'+Date.now()+'-'+Math.random().toString(16).slice(2,6),serviceId:payload.serviceId,barberId:payload.barberId,date:payload.date,time:payload.time,duration:service.minutes,status:'simulado',createdAt:new Date().toISOString()};db.bookings.push(item);save(db);return {ok:true,item}}
function price(v){return v===null||v===''||v===undefined?'Valor sob consulta':new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format(Number(v))}
window.LucasDemo={load,save,escape,dateKey,fromKey,datePlus,dateBr,hoursFor,availableSlots,addBooking,price,defaults,KEY};
})();
