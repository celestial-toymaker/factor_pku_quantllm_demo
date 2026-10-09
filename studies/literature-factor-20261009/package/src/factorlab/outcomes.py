"""Calendar endpoints and access control. Search never receives a final capability."""
from pathlib import Path
import json
import pandas as pd
from .common import append, now

class DataBoundaryError(RuntimeError):pass

def read_bars(root, purpose='validation', capability=None):
    root=Path(root)
    if purpose not in {'development','validation','final'}:raise DataBoundaryError('Unknown purpose')
    stage='history'
    if purpose=='final':
        if capability is None:raise DataBoundaryError('Final capability required')
        from .protocol import check_finalist
        frozen=check_finalist(root)
        if capability!=frozen['freeze_hash']:raise DataBoundaryError('Invalid final capability')
        append(root/'research/final_access.jsonl',{'time':now(),'purpose':purpose,'method':frozen['candidate_id']})
        stage='final'
    path=root/'private/processed'/f'{stage}_bars.parquet'
    df=pd.read_parquet(path)
    if purpose!='final' and (pd.to_datetime(df.date)>pd.Timestamp('2023-12-31')).any():
        raise DataBoundaryError('Search data contains dates outside historical boundary')
    return df

def calendar_labels(open_prices, horizon, segment_end, tradable=None):
    # Index is the exchange calendar. Missing endpoints stay missing, never compress rows.
    if tradable is not None:open_prices=open_prices.where(tradable)
    labels=open_prices.shift(-(horizon+1))/open_prices.shift(-1)-1
    dates=pd.Series(open_prices.index,index=open_prices.index).shift(-(horizon+1))
    return labels.where(dates.le(pd.Timestamp(segment_end)),axis=0)
