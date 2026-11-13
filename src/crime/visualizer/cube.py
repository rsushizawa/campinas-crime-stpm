"""Linked tract map, quarterly counts and Gi* significance histories."""
from __future__ import annotations

import html
import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from crime.models import SpaceTimeCube


@dataclass(frozen=True)
class CubeExplorer:
    """Portable document, rendered in an iframe in Jupyter and Colab.

    Leaflet and Plotly are loaded from versioned CDNs. No report coordinates,
    authentication credentials, or Python callback server are embedded.
    """

    document: str
    payload: dict

    def _repr_html_(self):
        return ('<iframe title="Space–time cube explorer" style="width:100%;height:920px;border:0" '
                'sandbox="allow-scripts allow-same-origin allow-downloads" '
                f'srcdoc="{html.escape(self.document, quote=True)}"></iframe>')


def cube_explorer(cube: SpaceTimeCube, tracts, *, bins=None, labels=None, alpha=0.05) -> CubeExplorer:
    """Align inference by tract and period; never confuse absent inference with NS.

    ``bins`` is EHSAResult.bins (z, p, p_bh), for this cube only. Categories in
    ``labels`` are descriptive EHSA outputs; their final FDR is not established
    by the bin adjustment. Count colour limits are fixed across all periods.
    """
    if not 0 < alpha < 1:
        raise ValueError('Require 0 < alpha < 1')
    if tracts.crs is None:
        raise ValueError('Tract geometry CRS must be known')
    id_col = 'census_tract_id' if 'census_tract_id' in tracts else 'unit_id'
    geo = tracts[[id_col, 'geometry']].copy()
    geo[id_col] = geo[id_col].astype(str)
    if geo[id_col].duplicated().any() or set(geo[id_col]) != set(cube.unit_ids):
        raise ValueError('Geometry IDs must match cube IDs exactly and uniquely')
    if geo.geometry.isna().any() or geo.geometry.is_empty.any():
        raise ValueError('Every cube unit needs a polygon')
    geo = geo.set_index(id_col).loc[list(cube.unit_ids)].to_crs(4326)
    geometry = json.loads(geo.to_json())
    periods = [p.isoformat() for p in cube.periods]
    inference = {}
    if bins is not None:
        d = bins.copy()
        d['unit_id'] = d.unit_id.astype(str)
        d['period'] = pd.to_datetime(d.period)
        if d.duplicated(['unit_id', 'period']).any():
            raise ValueError('Inference must have exactly one row per tract-period')
        expected = pd.MultiIndex.from_product([cube.unit_ids, cube.periods], names=['unit_id', 'period'])
        indexed = d.set_index(['unit_id', 'period'])
        if len(indexed) != len(expected) or not indexed.index.isin(expected).all():
            raise ValueError('Inference tract-period keys must match this cube exactly')
        aligned = indexed.reindex(expected)
        for col in ('z', 'p', 'p_bh'):
            values = aligned[col].to_numpy(dtype=float).reshape(cube.counts.shape)
            if col != 'z' and ((values[np.isfinite(values)] < 0).any()
                               or (values[np.isfinite(values)] > 1).any()):
                raise ValueError('Inference p-values must lie between zero and one')
            inference[col] = _numbers(values)
    categories = {}
    if labels is not None:
        d = labels.copy()
        d['unit_id'] = d.unit_id.astype(str)
        if d.unit_id.duplicated().any() or set(d.unit_id) != set(cube.unit_ids):
            raise ValueError('EHSA labels must match this cube exactly and uniquely')
        d = d.set_index('unit_id').loc[list(cube.unit_ids)]
        categories = {col: d[col].fillna('unavailable').astype(str).tolist()
                      for col in ('category', 'category_fdr') if col in d}
    payload = {'ids': list(cube.unit_ids), 'periods': periods, 'counts': _numbers(cube.counts),
               'geometry': geometry, 'inference': inference, 'categories': categories,
               'group': cube.crime_group, 'time_unit': cube.time_unit, 'alpha': alpha,
               'max_count': float(cube.counts.max(initial=0))}
    # JSON is script data, never markup; escape script terminators and invalid JS numbers.
    encoded = json.dumps(payload, allow_nan=False).replace('<', '\\u003c').replace('>', '\\u003e')
    document = _TEMPLATE.replace('__PAYLOAD__', encoded)
    return CubeExplorer(document, payload)


def _numbers(values):
    return np.where(np.isfinite(values), values, None).tolist()


_TEMPLATE = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Space–time cube explorer</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
body{font:14px system-ui,sans-serif;margin:14px;color:#182635;background:#fafbfc}
h1{font-size:19px;margin:0 0 10px}label{display:inline-block;margin:6px 14px 6px 0}
select,input,button{font:inherit;padding:5px;border:1px solid #adb8c2;border-radius:4px}
#slider{width:220px;vertical-align:middle}#grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
#map{height:570px;background:#eef0f2;border:1px solid #d4dbe1;border-radius:6px}
#series{height:290px}#history{height:180px}#summary{line-height:1.8;min-height:60px}
.note{font-size:12px;color:#495866;margin:9px 0}.legend span{display:inline-block;margin-right:14px}
.error{color:#9d1523}#scale{font-size:12px;padding:8px;background:#fff}
@media(max-width:850px){#grid{grid-template-columns:1fr}#map{height:360px}}
</style></head><body>
<h1>Police-recorded offences · space–time cube</h1>
<div id="status" class="note">Loading viewer libraries…</div>
<label>Period <input id="slider" type="range" min="0" value="0"><output id="period"></output></label>
<label>Map layer <select id="metric"><option value="count">Report count</option>
<option value="significance">Gi* significance</option><option value="z">Gi* z-score</option></select></label>
<label>Inference <select id="correction"><option value="p_bh">BH adjusted</option>
<option value="p">Raw (exploratory)</option></select></label>
<label>Tract <input id="tract" list="tracts" aria-label="Select tract"><datalist id="tracts"></datalist></label>
<div id="grid"><div><div id="map"></div><div id="scale"></div></div>
<div><div id="summary"></div><div id="series"></div><div id="history"></div></div></div>
<div class="legend note"><span style="color:#b2182b">■ Significant hot</span>
<span style="color:#2166ac">■ Significant cold</span><span style="color:#777">■ Not significant</span>
<span>□ Inference unavailable</span></div>
<p class="note">Click a tract to inspect its complete history; click either chart to select a period.
Colour limits stay fixed across periods. Gi* tests concern the space–time neighbourhood, not only the selected tract.
BH adjustment covers all tract-period bins in this analysis. EHSA trend tests are unadjusted;
this does not establish 5% FDR for the final EHSA categories.</p>
<script id="cube-data" type="application/json">__PAYLOAD__</script>
<script>
(function(){
const D=JSON.parse(document.getElementById('cube-data').textContent);
const el=id=>document.getElementById(id), finite=x=>typeof x==='number'&&Number.isFinite(x);
if(typeof L==='undefined'||typeof Plotly==='undefined'){
 el('status').textContent='Viewer libraries could not load. Allow access to unpkg.com and cdn.plot.ly, then reopen.';
 el('status').className='error';return;}
let t=0,i=0,layer=null;const ids=new Map(D.ids.map((id,i)=>[id,i]));
el('status').textContent=D.group+' · '+D.ids.length+' tracts · '+D.periods.length+' '+D.time_unit+' bins';
el('slider').max=D.periods.length-1;
for(const id of D.ids){let o=document.createElement('option');o.value=id;el('tracts').appendChild(o);}
const map=L.map('map',{preferCanvas:true});
const inf=D.inference,has=Object.keys(inf).length>0;
if(!has){el('metric').options[1].disabled=true;el('metric').options[2].disabled=true;
 el('correction').disabled=true;}
function sig(row,k,which){if(!has||!finite(inf.z[row][k])||!finite(inf[which][row][k]))return null;
 return inf[which][row][k]<D.alpha?(inf.z[row][k]>0?1:inf.z[row][k]<0?-1:0):0;}
const zmax=has?Math.max(1,...inf.z.flat().filter(finite).map(Math.abs)):1;
function style(f){const row=ids.get(f.id),metric=el('metric').value;let color='#ffffff';
 if(metric==='significance'){const s=sig(row,t,el('correction').value);
 color=s===1?'#b2182b':s===-1?'#2166ac':s===0?'#d9d9d9':'#ffffff';}
 else if(metric==='count'){const v=D.counts[row][t]/Math.max(1,D.max_count);
 color='rgb('+Math.round(240-205*v)+','+Math.round(247-125*v)+','+Math.round(255-82*v)+')';}
 else {const z=inf.z[row][t];if(finite(z)){const a=Math.min(1,Math.abs(z)/zmax);
 color=z>=0?'rgb(178,'+Math.round(230-206*a)+','+Math.round(230-187*a)+')':
 'rgb('+Math.round(230-197*a)+','+Math.round(230-128*a)+',172)';}}
 return{color:row===i?'#111827':'#788591',weight:row===i?2.4:0.4,fillColor:color,fillOpacity:0.85};}
layer=L.geoJSON(D.geometry,{style,onEachFeature:(f,l)=>{l.bindTooltip('Tract '+f.id);
 l.on('click',()=>{i=ids.get(f.id);draw();});}}).addTo(map);map.fitBounds(layer.getBounds());
function fmt(x){return finite(x)?x.toLocaleString(undefined,{maximumFractionDigits:4}):'unavailable';}
function draw(){
 el('period').textContent=D.periods[t].slice(0,10);el('slider').value=t;el('tract').value=D.ids[i];
 layer.setStyle(style);const metric=el('metric').value;
 el('scale').textContent=metric==='count'?'Reports per '+D.time_unit+': 0–'+D.max_count:
 metric==='z'?'Gi* z-score: −'+fmt(zmax)+' to '+fmt(zmax):
 'Significance threshold: '+D.alpha+'; '+(el('correction').value==='p_bh'?'BH adjusted p':'raw p (exploratory)');
 const y=D.counts[i],sum=y.reduce((a,b)=>a+b,0);let summary='Tract '+D.ids[i]+
 ' | selected count: '+fmt(y[t])+' | mean: '+fmt(sum/y.length)+' | min: '+Math.min(...y)+' | max: '+Math.max(...y);
 if(has)summary+=' | Gi* z: '+fmt(inf.z[i][t])+' | raw p: '+fmt(inf.p[i][t])+' | adjusted p: '+fmt(inf.p_bh[i][t]);
 const cat=D.categories[el('correction').value==='p_bh'?'category_fdr':'category'];
 if(cat)summary+=' | EHSA: '+cat[i];el('summary').textContent=summary;
 const layout={margin:{l:55,r:15,t:28,b:45},title:{text:'Selected tract: report counts',font:{size:14}},
 xaxis:{title:'Period'},yaxis:{title:'Reports',rangemode:'tozero'},
 shapes:[{type:'line',xref:'x',yref:'paper',x0:D.periods[t],x1:D.periods[t],y0:0,y1:1,line:{color:'#555',dash:'dot'}}]};
 Plotly.react('series',[{x:D.periods,y,type:'scatter',mode:'lines+markers',line:{color:'#237ab7'},
 marker:{size:7},hovertemplate:'%{x|%Y-%m}<br>Reports: %{y}<extra></extra>'}],layout,{responsive:true,displayModeBar:false});
 if(has){const rows=['p','p_bh'].map(k=>D.periods.map((_,j)=>sig(i,j,k)));
 const text=['p','p_bh'].map(k=>D.periods.map((_,j)=>'Gi* z: '+fmt(inf.z[i][j])+'<br>p: '+fmt(inf[k][i][j])));
 Plotly.react('history',[{type:'heatmap',x:D.periods,y:['Raw (exploratory)','BH adjusted'],z:rows,
 text,hovertemplate:'%{x|%Y-%m}<br>%{y}<br>%{text}<extra></extra>',zmin:-1,zmax:1,
 colorscale:[[0,'#2166ac'],[0.2499,'#2166ac'],[0.25,'#d9d9d9'],[0.7499,'#d9d9d9'],[0.75,'#b2182b'],[1,'#b2182b']],
 showscale:false,xgap:2,ygap:4,hoverongaps:false}],
 {margin:{l:120,r:15,t:35,b:35},title:{text:'Significance history',font:{size:14}},xaxis:{title:'Period'},
 yaxis:{autorange:'reversed'}},{responsive:true,displayModeBar:false});
 }else{el('history').textContent='Gi* inference has not been calculated for this cube. Counts alone do not establish hotspots.';}}
el('slider').oninput=e=>{t=Number(e.target.value);draw();};
el('metric').onchange=draw;el('correction').onchange=draw;
el('tract').onchange=e=>{if(ids.has(e.target.value)){i=ids.get(e.target.value);draw();}};
draw();function choosePeriod(e){if(e.points&&e.points.length){let k=e.points[0].pointIndex;
 if(Array.isArray(k))k=k[1];if(Number.isInteger(k)){t=k;draw();}}}
el('series').on('plotly_click',choosePeriod);if(has)el('history').on('plotly_click',choosePeriod);
})();
</script></body></html>'''
