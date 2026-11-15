import sys; sys.path.insert(0, "/Users/davemini2/ProjectsLocal/serp-compete/Serp-compete")
from src.semantic import SemanticAuditor
a = SemanticAuditor()
for txt in ["Self-regulation and self-regulation again.", "differentiation of self", "Pursuer-distancer reciprocity", "triangles triangulation", "over-under functioning"]:
    r = a.analyze_text(txt); print(f"{txt!r:45} t2={r['t2_count']} t3={r['t3_count']}")
