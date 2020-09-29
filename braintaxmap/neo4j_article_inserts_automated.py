# Author    Milain Lambers
# Github    Queuebee2

import os
import pickle

from py2neo import Graph, Node, Relationship

from braintaxmap.config import neo4j_URL, neo4j_db_creds
from braintaxmap.data_prep import flat_relations_hirarchy
from braintaxmap.data_prep import load_previous
from braintaxmap.data_processing import getmnemdef
from braintaxmap.querymachine import QueryMachine
from braintaxmap.tools import fuzz

DATA_DIR = ".." + os.sep + 'data' + os.sep
SOUGHT_TERM_FILENAME = DATA_DIR + 'sought_keywords.pickle'
ERROR_LOG_FILE = DATA_DIR + 'article_insert_error_log.txt'  # todo make error output dir

""" see readme
this script looks for articles (not checking if they exist, yet) and inserts them into the database

"""


def load_sought(filename=SOUGHT_TERM_FILENAME, reset=False):
    """Load list of used sought_keywords"""
    if reset:
        return set()
    try:
        with open(filename, 'rb') as infile:
            sought_keywords = pickle.load(infile)
            print('successfully loaded sought_keywords')
            return sought_keywords
    except FileNotFoundError:
        return set()


def save_sought(sought_keywords, filename=SOUGHT_TERM_FILENAME):
    """Load list of used sought_keywords"""
    with open(filename, 'wb') as outfile:
        pickle.dump(sought_keywords, outfile)
        print('successfully dumped(saved) sought_keywords')
        return True


def terms_generator(reset=False):
    """ yield keywords we haven't used yet"""

    keywords = load_sought(reset=reset)

    behaviors = iter(flat_relations_hirarchy().keys())
    structures = iter(load_previous().keys())
    prev = 'none'

    for (termgenerator, labels) in [(behaviors, ['function', 'behaviour']),
                                    (structures, ['brainstructure'])]:
        for term in termgenerator:
            while term not in keywords:
                yield term, labels
                # buffer if the program fails
                keywords.add(prev)
                save_sought(keywords)
                prev = term


def harvest_articles(amt=1, reset=False, searchlimit=10000):
    """ NOTE: NO word.lower() USED YET """
    print(f'starting to harvest {amt} articles. reset_keywords_sought = {reset}')

    keywords = terms_generator(reset=reset)

    q = QueryMachine()

    searches_done = 0
    articles_found = 0
    unique_pmids = set()
    unique_pmc = set()

    for word, labels in keywords:

        print(f'searching for: "{word}"')
        records = q.queryPubMed(word, searchlimit=searchlimit)
        for rec in records:

            articles_found += 1

            # todo: efficiencize
            # skip articles that are not in pmc
            # set false as default to prevent keyerror ?
            # what would be faster, keyerror > continue
            # or create False default > continue if still false
            # or check 'pmc' in keys...
            rec.setdefault('PMC', False)
            if not rec['PMC']:
                continue

            # set defaults for nonoccuring mnemonics
            # for mnemonic_key, interpretation in mnemonic_definitions.items():
            # rec.setdefault(mnemonic_key,'')

            # for the database, the mnemonics might not be the most readable...
            # rec = {k:v for k,v in rec.items() if v!= ''}

            unique_pmc.add(rec['PMC'])
            unique_pmids.add(rec['PMID'])

            if articles_found % 100 == 0:
                print(f'articles found: {articles_found}')
                print(f'unique pmid: {len(unique_pmids)}')
                print(f'unique pmc: {len(unique_pmc)}')
                print(60 * "-")

            yield (word, labels), rec

        searches_done += 1
        if searches_done % 2 == 0:
            print(f'searches executed: {searches_done}')

    print(f'All searches executed, total:{searches_done}')
    print(f'Total articles found: {articles_found}')


def harvest_and_insert(amt=5, reset=False, searchlimit=100):
    graph = Graph(neo4j_URL, auth=neo4j_db_creds)  # more on Graph class ; https://py2neo.org/v5/database.html

    # harvester automatically gets non-used terms (if reset=False)
    # and yields new records
    article_harvester = harvest_articles(amt=amt, reset=reset, searchlimit=searchlimit)

    # definitions of mnemonic keys, e.g. 'MH' == 'Mesh Terms'
    mnemonic_definitions = getmnemdef()  # grab definitions of mnemonics

    ARTICLE_OF = Relationship.type('ARTICLE_OF')
    CITED_IN = Relationship.type('CITED_IN')  # UNUSED SO FAR.

    for (word, labels), record in article_harvester:
        word_is_parent = Node(*labels, name=word)
        word_is_parent.__primarylabel__ = labels[0]
        word_is_parent.__primarykey__ = 'name'

        article = Node('article', PMC_ID=record['PMC'], **record)
        article.__primarylabel__ = 'article'
        article.__primarykey__ = 'PMC'

        graph.merge(ARTICLE_OF(article, word_is_parent))

        print(word, record['PMC'])

        fuzz(0.05)

    print('done inserting nodes')


from datetime import datetime


def logerror(e):
    with open(ERROR_LOG_FILE, 'a') as out:
        out.write(datetime.now().strftime(
            "%I:%M%p %B %d, %Y") + " :\t" + str(e) + "\n")


if __name__ == '__main__':
    from Bio import Entrez
    from braintaxmap.config import dev_email

    Entrez.email = dev_email

    amount = 10000
    print('starting inserts')
    runs = 0
    while runs < 10:
        try:
            harvest_and_insert(amount, reset=False, searchlimit=1000)
        except Exception as e:
            logerror(e)
            runs += 1
            fuzz()

    print('done running main')
