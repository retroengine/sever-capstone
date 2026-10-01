****Norm check on all three datasets: 0 non-finite and 0 outside tolerance, worst deviation 1.84e-7 against a limit of 9.5e-7. Row counts match their tables****

**script located at :** *python/sever_demo/data.py*
*results recorded at 26-09-2026 11:21AM*

**saiki@lappot:/mnt/c/Users/saiki/final-vdb$ uv run python python/sever_demo/data.py**
      
    === sciq_reference ===
    npy shape: (13679, 384) | dtype: float32
    parquet rows: 13679
    parquet columns: ['id', 'text']
    rows match: True
      parquet row 0: {'id': 'sciq-train-000000', 'text': 'Mesophiles grow best in moderate temperature, typically between 25°C a...'}
      parquet row 1: {'id': 'sciq-train-000001', 'text': 'Without Coriolis Effect the global winds would blow north to south or ...'}
      parquet row 2: {'id': 'sciq-train-000002', 'text': 'Summary Changes of state are examples of phase changes, or phase trans...'}
    norm check: {'rows': 13679, 'non_finite': 0, 'bad_length': 0, 'worst_abs_diff': 1.3911157448198708e-07, 'first_bad_rows': []}
    
    === nq_1m ===
    npy shape: (1000000, 384) | dtype: float32
    parquet rows: 1000000
    parquet columns: ['row', 'corpus_index', 'id', 'cohort', 'text', 'judged']
    rows match: True
      parquet row 0: {'row': '0', 'corpus_index': '0', 'id': 'doc0', 'cohort': 'Minority interest', 'text': 'Minority interest In accounting, minority interest (or non-controlling...', 'judged': 'True'}
      parquet row 1: {'row': '1', 'corpus_index': '1', 'id': 'doc1', 'cohort': 'Minority interest', 'text': 'Minority interest It is, however, possible (such as through special vo...', 'judged': 'True'}
      parquet row 2: {'row': '2', 'corpus_index': '6', 'id': 'doc6', 'cohort': 'Chicago Fire (season 4)', 'text': 'Chicago Fire (season 4) The fourth season of Chicago Fire, an American...', 'judged': 'True'}
    norm check: {'rows': 1000000, 'non_finite': 0, 'bad_length': 0, 'worst_abs_diff': 1.8363731424386742e-07, 'first_bad_rows': []}
     
    === nq_queries ===
    npy shape: (3452, 384) | dtype: float32
    parquet rows: 3452
    parquet columns: ['query_id', 'text']
    rows match: True
      parquet row 0: {'query_id': 'test0', 'text': 'what is non controlling interest on balance sheet'}
      parquet row 1: {'query_id': 'test1', 'text': 'how many episodes are in chicago fire season 4'}
      parquet row 2: {'query_id': 'test10', 'text': 'when is the new tappan zee bridge going to be finished'}
    norm check: {'rows': 3452, 'non_finite': 0, 'bad_length': 0, 'worst_abs_diff': 1.313230801880394e-07, 'first_bad_rows': []}