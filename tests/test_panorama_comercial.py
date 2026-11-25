"""Exemplos sintéticos de compensação, dependência e validação temporal."""
import unittest

import numpy as np
import pandas as pd

from panorama_comercial import comparar, fluxos, indicadores, prever, razoes_produtos, respostas_municipais


class Panorama(unittest.TestCase):
    def test_compensacao_apenas_no_mesmo_produto(self):
        idx = pd.MultiIndex.from_tuples([("A","0001"),("A","0002"),("B","0001")],
                                        names=["CO_MUN","SH4"])
        a = pd.DataFrame({"eua":[10,0,0],"outros":[2,0,0],"kg_eua":[2,0,0],"kg_outros":[1,0,0]},index=idx)
        b = a.copy()
        b["eua"] = [0,0,20]
        b["outros"] = [5,30,0]
        mun = respostas_municipais(comparar({"a":a,"b":b},"a","b"))
        self.assertEqual(mun.loc["A","compensacao_mesmo_sh4_pct"],30)
        self.assertTrue(np.isnan(mun.loc["B","variacao_eua_pct"]))
        self.assertTrue(np.isnan(mun.loc["B","compensacao_mesmo_sh4_pct"]))
        p = razoes_produtos(b)
        self.assertTrue(p.loc[("B","0001"),"exclusivo_eua"])
        self.assertTrue(np.isnan(p.loc[("B","0001"),"razao_eua_outros"]))

    def test_indicador_usa_total_municipal(self):
        linhas = []
        for mes in pd.period_range("2022-01","2024-12",freq="M"):
            for sh,pais,valor in [("0901","249",30),("7201","249",20),("0901","063",50)]:
                linhas.append(("3100001","MG",sh,pais,mes.year,mes.month,valor,1))
        d = pd.DataFrame(linhas,columns=["CO_MUN","SG_UF_MUN","SH4","CO_PAIS","CO_ANO","CO_MES","VL_FOB","KG_LIQUIDO"])
        d["mercado"] = np.where(d.CO_PAIS=="249","eua","outros")
        t = indicadores(d,fluxos(d,["CO_MUN","SH4"])).iloc[0]
        self.assertEqual(t.vulnerabilidade_pct,30)
        self.assertEqual(t.sh4_principal_eua,"0901")
        self.assertEqual(t.participacao_eua,.5)

    def test_previsao_respeita_origem_e_selecao(self):
        idx = pd.period_range("2015-01","2026-10",freq="M")
        y = pd.DataFrame({"eua":100+np.arange(len(idx)), "outros":30+np.arange(len(idx))%12},index=idx)
        p,m,e = prever(y)
        self.assertEqual(p.mes.min(),idx[-1]+1)
        z = y.copy()
        z.loc["2025-01":] *= 2
        _,mz,ez = prever(z)
        pd.testing.assert_frame_equal(m[m.etapa=="selecao"],mz[mz.etapa=="selecao"])
        pd.testing.assert_series_equal(e.loc[e.origem=="2024-12","previsto"],ez.loc[ez.origem=="2024-12","previsto"])
        w = p.pivot(index="mes",columns="mercado",values="fob_usd")
        np.testing.assert_allclose(w.total,w.eua+w.outros)
