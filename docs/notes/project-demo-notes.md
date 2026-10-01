
"Normalised" means each row has length exactly 1. Length is computed like this:
    
Normalization is the process of taking a vector and scaling it down so that its geometric length becomes exactly 1. A vector with a length of 1 is called a unit vector.
      
length = √( x₁² + x₂² + … + x₃₈₄² )
     
Square every number in the row, add them up, take the square root. project's integer arithmetic (Q24) assumes every row has length about 1. If a row has length 5, it breaks the overflow bound in your spec. So you check every row and count the failures.

Sucessfully implemented validation of datasets embeding in folder nq_1m : embedding.npy , found that no violations of length 1 normalisations 

output log : {'rows': 1000000, 'non_finite': 0, 'bad_length': 0, 'worst_abs_diff': 1.8363731424386742e-07, 'first_bad_rows': []}
source: data.py , data:nq_1m 
finding: The worst row is only about 1.5 float32 steps from length 1

details = {
    Norm check on all 1,000,000 NQ vectors: 0 non-finite, 0 outside tolerance, worst deviation 1.84e-7 against a limit of 9.5e-7.

    One step is 2**-23, about 1.19e-7.

    total tolerance is 8 steps 
}
 
Ran other testt on all the datasets too :
result = {
    saiki@lappot:/mnt/c/Users/saiki/final-vdb$ uv run python python/sever_demo/data.py
 
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
norm check: {'rows': 3452, 'non_finite': 0, 'bad_length': 0, 'worst_abs_diff': 1.313230801880394e-07, 'first_bad_rows':[]}
}
 
Norm check on all three datasets: 0 non-finite and 0 outside tolerance, worst deviation 1.84e-7 against a limit of 9.5e-7. Row counts match their tables
 
  