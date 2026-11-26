"""Modelos municipais de associação. Erros robustos e diagnósticos por especificação."""
from math import erfc, exp, sqrt

import numpy as np
import pandas as pd


def ajustar(dados, y, termos, familia="linear", **descricao):
    t = dados[["CO_MUN", y, *termos]].replace([np.inf,-np.inf],np.nan).dropna()
    nomes = ["constante", *termos]
    x = np.column_stack([np.ones(len(t)),t[termos].to_numpy(dtype=float)])
    obs = t[y].to_numpy(dtype=float)
    if familia not in ("linear","logit","fracional"):
        raise ValueError(f"Família desconhecida: {familia}")
    logit = familia != "linear"
    diag = dict(**descricao, familia=familia, desfecho=y,n=len(t),parametros=len(nomes),
                n_zero=int(sum(obs==0)),n_cem=int(sum(obs==100)),status="estimado")
    if len(t)<=len(nomes) or np.linalg.matrix_rank(x)<len(nomes) or len(np.unique(obs))<2:
        return pd.DataFrame(),dict(diag,status="sem_variacao_posto_ou_amostra")
    std = x[:,1:].std(axis=0)
    z = (x[:,1:]-x[:,1:].mean(axis=0))/std
    inversa_padronizada = np.linalg.pinv(z)
    vif = len(t)*(inversa_padronizada**2).sum(axis=1)
    diag["vif_max"] = vif.max()
    diag["numero_condicao_padronizado"] = np.linalg.cond(z)
    if diag["vif_max"] > 1e6:
        return pd.DataFrame(),dict(diag,status="colinearidade_extrema")
    if logit:
        if familia == "logit" and not np.isin(obs,[0,100]).all():
            raise ValueError("Logit exige indicador binário de queda.")
        if not np.all((obs>=0)&(obs<=100)):
            raise ValueError("O desfecho fracional precisa estar entre zero e cem.")
        obs = obs/100
        beta = np.zeros(x.shape[1])
        for _ in range(80):
            mu = 1/(1+np.exp(-np.clip(x@beta,-45,45)))
            w = mu*(1-mu)
            info = (x.T*w)@x
            if np.linalg.matrix_rank(info)<len(nomes):
                return pd.DataFrame(),dict(diag,status="informacao_singular")
            passo = np.linalg.solve(info,x.T@(obs-mu))
            beta += passo
            if np.max(np.abs(passo))<1e-8:
                break
        else:
            return pd.DataFrame(),dict(diag,status="sem_convergencia")
        mu = 1/(1+np.exp(-np.clip(x@beta,-45,45)))
        w = mu*(1-mu)
        if min(w)<1e-12:
            return pd.DataFrame(),dict(diag,status="probabilidade_extrema")
    else:
        beta = np.linalg.lstsq(x,obs,rcond=None)[0]
        mu, w = x@beta, np.ones(len(t))
    residuo = obs-mu
    bread = np.linalg.inv((x.T*w)@x)
    h = np.einsum("ij,ji->i",x,bread@x.T)*w
    if h.max()>=1-1e-10:
        return pd.DataFrame(),dict(diag,status="alavancagem_unitaria")
    escore = x*(residuo/(1-h))[:,None]
    cov = bread@(escore.T@escore)@bread
    ep = np.sqrt(np.maximum(0,np.diag(cov)))
    diag["alavancagem_max"] = h.max()
    if not logit:
        mse = (residuo@residuo)/(len(t)-len(nomes))
        if mse>0:
            cook = residuo**2*h/(len(nomes)*mse*(1-h)**2)
            diag.update(cook_max=cook.max(),municipio_cook_max=t.CO_MUN.iloc[cook.argmax()],
                        n_cook_maior_4_n=int(sum(cook>4/len(t))))
    idx = [i for i,n in enumerate(nomes) if n.startswith("perfil_")]
    if len(idx)==4 and np.linalg.matrix_rank(cov[np.ix_(idx,idx)])==4:
        wald = float(beta[idx]@np.linalg.solve(cov[np.ix_(idx,idx)],beta[idx]))
        diag.update(wald_perfis=wald,gl_wald=4,p_conjunto_perfis=exp(-wald/2)*(1+wald/2))
    p = [erfc(abs(b/se)/sqrt(2)) if se>0 else np.nan for b,se in zip(beta,ep)]
    tabela = pd.DataFrame(dict(termo=nomes,coef=beta,ep_hc3=ep,ic025=beta-1.96*ep,ic975=beta+1.96*ep,
                               p_valor=p,vif=[np.nan,*vif],n=len(t),desfecho=y,familia=familia,**descricao))
    return tabela, diag
