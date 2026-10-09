# Implementation reference

The implemented directed lag-one return statistic is adapted from Bennett, Cucuringu and Reinert (2022), [Lead–lag detection and network clustering for multivariate time series with an application to the US equity market](https://arxiv.org/abs/2201.08283), version 1, pages 4–6. The original source is credited for the dependence statistic. The implemented study uses the exact equations in `research/method.md` and the six registered variants in `configs/candidate_registry.json`.

The tested construction estimates positive lag-one directional dependence, retains incoming links, and combines leaders' exponentially smoothed log returns. Expanding refits and direct weighted aggregation are the adaptation evaluated here. The source PDF is not redistributed.
