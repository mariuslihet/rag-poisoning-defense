"use strict";

function parseCampaignSweep(text,min,max,integer=false) {
  if(!text.trim())return null;
  const parts=text.trim().split(/[,\s]+/).filter(Boolean);
  if(!parts.length || parts.length>10)throw new Error("Enter 1–10 values for each parameter sweep.");
  const values=parts.map(part=>{
    if(!/^(?:\d+(?:\.\d*)?|\.\d+)$/.test(part))throw new Error("Sweep values must be ordinary non-negative decimal numbers.");
    const value=Number(part);
    if(!Number.isFinite(value) || value<min || value>max || (integer && !Number.isInteger(value)))throw new Error(`Sweep values must be ${integer ? "whole numbers ":""}from ${min} to ${max}.`);
    return value;
  });
  if(new Set(values).size!==values.length)throw new Error("Sweep values must be unique.");
  return values;
}

function campaignMatrixSize(body) {
  return body.models.length*body.policies.length*body.seeds.length*
    (body.thresholds?.length || 1)*(body.retrieval_depths?.length || 1)*(body.temperatures?.length || 1)*(body.retrieval_variants?.length || 1);
}

if(typeof module!=="undefined" && module.exports)module.exports={parseCampaignSweep,campaignMatrixSize};
