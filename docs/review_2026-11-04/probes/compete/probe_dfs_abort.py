"""main.run_audit: dfs_client.get_relevant_pages raising (no retry, no try) aborts the whole run AFTER create_run -> orphan run row; a non-200 returns [] and the domain vanishes with no report trace."""
import ast, inspect, sys
sys.path.insert(0, "/Users/davemini2/ProjectsLocal/serp-compete/Serp-compete")
src = open("/Users/davemini2/ProjectsLocal/serp-compete/Serp-compete/src/main.py").read()
tree = ast.parse(src)
fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_audit")
# find the call line and whether any enclosing Try covers it
call_line = next(n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "get_relevant_pages")
tries = [t for t in ast.walk(fn) if isinstance(t, ast.Try) and t.lineno <= call_line <= t.end_lineno]
print("get_relevant_pages call at main.py line", call_line, "| enclosing try blocks:", len(tries))
import src.api_clients as ac
s = inspect.getsource(ac.DataForSEOClient.get_relevant_pages)
print("retry loop in get_relevant_pages:", "for attempt" in s, "| exception handling:", "except" in s)
