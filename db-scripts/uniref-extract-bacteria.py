
import argparse
import gzip
from lxml import etree as et
from pathlib import Path

from Bio import SeqIO


parser = argparse.ArgumentParser(
    description='Filter Uniprot\'s UniRef90 XML files to bacterial subsequences and init pc db.'
)
parser.add_argument('--taxonomy', action='store', help='Path to NCBI taxonomy node.dmp file.')
parser.add_argument('--xml', action='store', help='Path to UniRef xml file.')
parser.add_argument('--uniparc', action='store', help='Path to UniParc fasta file.')
parser.add_argument('--fasta', action='store', help='Path to MPS fasta file.')
parser.add_argument('--tsv', action='store', help='Path to MPS tsv file.')
args = parser.parse_args()

taxonomy_path = Path(args.taxonomy).resolve()
xml_path = Path(args.xml).resolve()
uniparc_path = Path(args.uniparc).resolve()
fasta_path = Path(args.fasta)
tsv_path = Path(args.tsv)


def is_taxon_child(child, LCA, taxonomy):
    parent = taxonomy.get(child, None)
    while(parent is not None and parent != '1'):
        if(parent == LCA):
            return True
        else:
            parent = taxonomy.get(parent, None)
    return False


taxonomy = {}
with taxonomy_path.open() as fh:
    for line in fh:
        cols = line.split('\t|\t', maxsplit=2)
        taxonomy[cols[0]] = cols[1]

uniref90_uniparc_ids = {}

with fasta_path.open(mode='wt') as fh_fasta, tsv_path.open(mode='wt') as fh_tsv:
    with gzip.open(str(xml_path), mode='rb') as fh_xml:
        i = 0
        for event, elem in et.iterparse(fh_xml, tag='{*}entry'):
            if('Fragment' not in elem.find('./{*}name').text):  # skip protein fragments
                common_tax_id = elem.find('./{*}property[@type="common taxon ID"]')
                common_tax_id = common_tax_id.get('value') if common_tax_id is not None else 1

                rep_member_dbref = elem.find('./{*}representativeMember/{*}dbReference')
                rep_member_organism = rep_member_dbref.find('./{*}property[@type="source organism"]')  # source organism
                rep_member_organism = rep_member_organism.get('value') if rep_member_organism is not None else ''

                rep_member_tax_id = rep_member_dbref.find('./{*}property[@type="NCBI taxonomy"]')
                rep_member_tax_id = rep_member_tax_id.get('value') if rep_member_tax_id is not None else 1

                # filter for bacterial or phage protein sequences
                if(is_taxon_child(common_tax_id, '2', taxonomy) or is_taxon_child(rep_member_tax_id, '2', taxonomy) or 'phage' in rep_member_organism.lower()):
                    # print(f'tax-id={tax_id}')
                    uniref90_id = elem.attrib['id'][9:]  # remove 'UniRef90_' prefix

                    rep_member = elem.find('./{*}representativeMember')
                    rep_member_dbref = rep_member.find('./{*}dbReference')
                    prot_name = rep_member_dbref.find('./{*}property[@type="protein name"]')
                    prot_name = prot_name.attrib['value'] if prot_name is not None else ''

                    # lookup seed sequence
                    is_seed = rep_member_dbref.find('./{*}property[@type="isSeed"]')
                    if(is_seed is not None):  # representative is seed sequence
                        seq = rep_member.find('./{*}sequence').text.upper()
                        fh_fasta.write(f'>{uniref90_id}\n{seq}\n')
                        fh_tsv.write(f'{uniref90_id}\t{prot_name}\t{len(seq)}\n')
                    else:  # search for seed member
                        for member_dbref in elem.findall('./{*}member/{*}dbReference'):
                            if(member_dbref.find('./{*}property[@type="isSeed"]') is not None):
                                uniparc_id = member_dbref.find('./{*}property[@type="UniParc ID"]')  # search for UniParc annotation
                                if(uniparc_id is not None):  # use UniParc ID
                                    seed_db_type = 'UniParc ID'
                                    seed_db_id = uniparc_id.attrib['value']
                                else:  # use DBRef type (either UniParc or UniProtKB)
                                    seed_db_type = member_dbref.get('type')
                                    seed_db_id = member_dbref.get('id')
                                
                                if(seed_db_type == 'UniParc ID'):
                                    uniref90_uniparc_ids[seed_db_id] = (uniref90_id, prot_name)
                                else:
                                    print(f'detected additional seed type! UniRef90-id={uniref90_id}, seed-type={seed_db_type}, seed-id={seed_db_id}')
                                break
                            member_dbref.clear()
            i += 1
            if((i % 1000000) == 0):
                print(f'{i}...')
            elem.clear()  # forstall out of memory errors

    print('Lookup non-representative seed sequences in:')
    print(f'UniParc ({len(uniref90_uniparc_ids)})...')
    i = 0
    with gzip.open(str(uniparc_path), mode='rt') as fh_uniparc, fasta_path.open(mode='at') as fh_fasta:
        for record in SeqIO.parse(fh_uniparc, 'fasta'):
            if(record.id in uniref90_uniparc_ids):
                (uniref90_id, prot_name) = uniref90_uniparc_ids.get(record.id, None)
                seq = str(record.seq).upper()
                fh_fasta.write(f'>{uniref90_id}\n{seq}\n')
                fh_tsv.write(f'{uniref90_id}\t{prot_name}\t{len(seq)}\n')
                uniref90_uniparc_ids.pop(record.id)
                i += 1
    print('\twritten UniParc seed sequences: {i}')