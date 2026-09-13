"""RDF vocabulary IRIs used outside query templates."""

from app.sparql.terms import Iri

AOPO = "http://aopkb.org/aop_ontology#"
NCI = "http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl#"
CHEMINF = "http://semanticscience.org/resource/CHEMINF_"
NCBITAXON = "http://purl.bioontology.org/ontology/NCBITAXON/"
IDENTIFIERS = "https://identifiers.org/"

AOP_TYPE = Iri(f"{AOPO}AdverseOutcomePathway")
KEY_EVENT_TYPE = Iri(f"{AOPO}KeyEvent")
KER_TYPE = Iri(f"{AOPO}KeyEventRelationship")
STRESSOR_TYPE = Iri(f"{NCI}C54571")
CHEMICAL_TYPE = Iri(f"{CHEMINF}000000")
