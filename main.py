import argparse
import datetime
import json
import logging
import math
import sys
from typing import List, Dict

import pandas as pd
# https://pypi.org/project/phonenumbers/
import phonenumbers
from pandas import DataFrame
from phonenumbers import carrier, PhoneNumber
from pytimeparse.timeparse import timeparse


def parseNumber(nr: str) -> PhoneNumber:
    nr = str(nr)
    # print("Parsing nr [{}]".format(nr))
    if nr.startswith('06'):
        nr = "+36" + nr[2:]
    if len(nr) == 11 and not nr.startswith("+"): nr = "+" + nr
    # Hordozott szám :(
    if nr == "+36301837880": nr = "+36201837880"
    if nr == 'nan': nr = "+36201837880"  # hidden number
    return phonenumbers.parse(nr, region="HU")


class Tarifa:
    # yearMonth = -1
    # maradek_ingyen_percek = 0
    # maradek_ingyen_percek_sajat = 0

    # last_cr_date = datetime.datetime.strptime("1970 01 01", "%Y %m %d")

    @staticmethod
    def load(fle: str):
        logging.info(f"Loading file {fle}...")
        with open(fle, encoding='utf8') as file:
            data = json.load(file)
        return [Tarifa(e) for e in data["tarifak"]]

    def __init__(self, params={}):
        # print("params: " + str(params))
        self.desc = params.get("desc", "")
        self.carrier = params.get("carrier", None)

        self.base = params.get("base", 'perc')
        self.alap_dij = int(params.get("alap_dij", 0))
        self.ingyen_percek = params.get("ingyen_percek", 0)
        self.ingyen_percek_sajat = params.get("ingyen_percek_sajat", 0)
        self.ingyen_percek_eu = params.get("ingyen_percek_eu", None)

        self.perc_dij = int(params.get("perc_dij", 0))
        self.netGB = int(params.get("netGB", 0))

    def __str__(self):
        r = f"Név:{self.desc}\n"
        r += f"Szolg:{self.carrier}\n"
        r += f"Alapdíj:{self.alap_dij}\n"
        r += f"Számlázás alapja:{self.base}\n"
        r += f"Ingyen percek:{self.ingyen_percek}\n"
        r += f"Ingyen percek hálózaton belül:{self.ingyen_percek_sajat}\n"
        r += f"Percdíj: {self.perc_dij} Ft\n"
        r += f"Mobilnet: {self.netGB}GB\n"
        r += f""
        return r

    def get_pandas_data(self, type: str = "") -> list:
        if type == 'header':
            retval = ['Szolgáltató', 'Alapdíj', 'Számlázás alapja', 'Ingyen percek',
                      'Ingyen percek hál. belül', 'Ingyen percek EU', 'Percdíj', 'Mobilnet[GB]']
        else:
            retval = [self.carrier, self.alap_dij, self.base, self.ingyen_percek,
                      self.ingyen_percek_sajat, self.ingyen_percek_eu, self.perc_dij, self.netGB]
        return retval


class CallRecord:

    @staticmethod
    def load(fle: str):
        logging.info(f"Loading file {fle}...")
        callRecords = [CallRecord(line) for line in reversed(import_csv(fle))]
        for i in range(len(callRecords)):
            cr: CallRecord = callRecords[i]
            cr.id = i

        return callRecords

    def __init__(self, dict):
        # print(dict)
        self.fromName = dict["Name"]
        self.type = dict["Type"]
        try:
            self.toNumber = parseNumber(dict["To Number"])
        except phonenumbers.phonenumberutil.NumberParseException as err:
            logging.error(f" Error parsing number [{dict['To Number']}]: {err.args}")
            self.type = 'ERROR_PARSING_NUMBER'
            self.toCarrier = 'bla'
        else:
            self.toCarrier = carrier.name_for_number(self.toNumber, 'hu', region="HU")
        try:
            self.fromNumber = parseNumber(dict["From Number"])
        except phonenumbers.phonenumberutil.NumberParseException as err:
            logging.error(f" Error parsing number [{dict['From Number']}]: {err.args}")
            self.type = 'ERROR_PARSING_NUMBER'
            self.fromCarrier = 'bla'
        else:
            self.fromCarrier = carrier.name_for_number(self.fromNumber, 'hu', region="HU")

        self.belfoldi_hivas = self.fromNumber.country_code == self.toNumber.country_code
        self.halozaton_beluli_hivas = self.belfoldi_hivas and (self.fromCarrier == self.toCarrier)

        self.id = "0"

        f = "{} {}".format(dict["Date"], dict["Time"])
        self.start = datetime.datetime.strptime(f, "%Y-%m-%d %I:%M %p")
        self.epoch = int(self.start.timestamp())
        self.yearMonth = self.start.strftime("%Y.%m")
        self.end = self.start + datetime.timedelta(0, timeparse(str(dict["Duration"])))
        self.duration = self.end - self.start
        self.hossz_perc = math.ceil(self.duration.seconds / 60)
        self.szamolt_dij = None

    def __repr__(self):
        r = "{}, {} perc, ".format(self.start, self.hossz_perc)
        r += "irány: {},".format(self.type)
        r += "díj: {} Ft,".format(self.szamolt_dij)
        return r


class Bill:
    def __init__(self, tarifa: Tarifa, callRecords: List[CallRecord] = []):
        self.reszletek = {}
        self.tarifa = tarifa
        self.last_cr_date = None
        self.yearMonth = None
        self.callRecords = {}
        [self.add_call_record(x) for x in callRecords]

        self.maradek_ingyen_percek = tarifa.ingyen_percek
        self.maradek_ingyen_percek_sajat = tarifa.ingyen_percek_sajat
        # self.fizetendo = {}  # self.tarifa.alap_dij
        # self.summary = 0

        self.recalculate_all()

    def add_call_record(self, callRecord: CallRecord, do_billing=True):
        if self.yearMonth is None:
            self.yearMonth = callRecord.yearMonth
        else:
            if self.yearMonth != callRecord.yearMonth:
                logging.error("Ez a hívás nem ebbe a hónapba tartozik.")
                sys.exit(1)
        if callRecord.epoch in self.callRecords:
            logging.debug("Double call records for the same time???")
            # sys.exit(1)
            callRecord.epoch += 1
        self.callRecords[callRecord.epoch] = callRecord
        if do_billing: self.bill(callRecord)

    def bill(self, callRecord: CallRecord):
        logging.info(f"get_szamolt_dij({callRecord}, {self.tarifa.carrier} - {self.tarifa.desc})")
        cid = callRecord.id
        if cid in self.reszletek:
            logging.info("Már kiszámolva.")
            return self.reszletek[callRecord.id]['fizetendo']

        self.reszletek[cid] = {}
        self.reszletek[cid]['fizetendo'] = 0

        if self.last_cr_date is not None and self.last_cr_date > callRecord.start:
            raise Exception(
                "Error: nem időrendi sorrendben érkeznek be a rekordok, így nem lehet feldolgozni őket.\n{}".format(
                    callRecord))
        self.last_cr_date = callRecord.start
        # self.fizetendo[callRecord.id] = 0

        if callRecord.type != 'Outgoing': return 0
        if callRecord.hossz_perc == 0: return 0

        halozaton_belul = self.tarifa.carrier == callRecord.toCarrier
        perc_dij = self.tarifa.perc_dij
        fizetendo_perc = callRecord.hossz_perc

        if halozaton_belul:
            logging.info("Ez egy hálózaton belüli hívás.")
            if self.maradek_ingyen_percek_sajat > 0:
                if fizetendo_perc <= self.maradek_ingyen_percek_sajat:
                    # elég a keret
                    self.maradek_ingyen_percek_sajat = \
                        self.maradek_ingyen_percek_sajat \
                        - \
                        fizetendo_perc
                    fizetendo_perc = 0
                    logging.info(
                        "{} ingyen perc elhasználva, marad még {} ingyen perc saját hálózaton belül.".format(
                            callRecord.hossz_perc, self.maradek_ingyen_percek_sajat))
                else:
                    # nem elég a keret
                    fizetendo_perc = fizetendo_perc - self.maradek_ingyen_percek_sajat
                    self.maradek_ingyen_percek_sajat = 0
                    logging.info(
                        "{} ingyen perc elhasználva, viszont ezzel elfogyott a saját hálózaton belüli ingyen perc, sőt, még {} elszámolandó.".format(
                            1, 2))

        if fizetendo_perc > 0:
            if self.maradek_ingyen_percek > 0:
                if fizetendo_perc <= self.maradek_ingyen_percek:
                    self.maradek_ingyen_percek = self.maradek_ingyen_percek - \
                                                 fizetendo_perc
                    fizetendo_perc = 0
                    logging.info(
                        "Marad még {} ingyen perc".format(self.maradek_ingyen_percek))
                else:
                    fizetendo_perc = fizetendo_perc - self.maradek_ingyen_percek
                    self.maradek_ingyen_percek = 0
                    logging.info(
                        "Ezzel elfogyott az ingyen perc, {} percet fizetni kell.".format(
                            fizetendo_perc))

        self.reszletek[cid]['fizetendo_perc'] = fizetendo_perc
        self.reszletek[cid]['percdij'] = perc_dij
        self.reszletek[cid]['fizetendo'] = fizetendo_perc * perc_dij

        return self.reszletek[cid]['fizetendo']

    def recalculate_all(self):
        for callRecord in self.callRecords:
            self.bill(callRecord)

        # self.summary = sum([x.get_szamolt_dij(tarifa=self.tarifa) for x in
        #                     self.callRecords])

    def get_mindosszesen(self):
        mindosszesen = 0
        mindosszesen += self.tarifa.alap_dij
        for x in self.reszletek.values():
            if 'fizetendo' in x: mindosszesen += x['fizetendo']
        self.mindosszesen = mindosszesen
        return mindosszesen


def import_csv(fle: str):
    # return [tuple(x) for x in df.values]
    # return [[row[col] for col in df.columns] for row in df.to_dict('records')]
    return pd.read_csv(fle, dtype=str, delimiter=',').to_dict('records')


class Billing:
    def __init__(self, tarifak_file: str, call_records_file: str):
        self.tarifak = Tarifa.load(tarifak_file)
        self.call_records = CallRecord.load(call_records_file)
        self.bills: Dict[Bill] = {}
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', None)
        pd.options.display.float_format = '{:.0f}'.format

    def create_bills(self):
        for tarifa in self.tarifak:
            for call_record in self.call_records:
                if call_record.yearMonth not in self.bills:
                    self.bills[call_record.yearMonth] = {}

                if tarifa.desc not in self.bills[call_record.yearMonth]:
                    self.bills[call_record.yearMonth][tarifa.desc]: Bill = Bill(tarifa=tarifa)
                b: Bill = self.bills[call_record.yearMonth][tarifa.desc]
                b.add_call_record(call_record)

        for yearMonth in self.bills:
            for tarifa in self.bills[yearMonth]:
                bill: Bill = self.bills[yearMonth][tarifa]
                bill.get_mindosszesen()

        self._create_pd_data()

    def report_tarifa(self):
        print("Tarifák:")
        data = {}
        header = None
        for tarifa in self.tarifak:
            if header is None:
                header = tarifa.get_pandas_data(type='header')
            data[f"{tarifa.desc}"] = tarifa.get_pandas_data()
        df = pd.DataFrame(data, index=header)
        print(df)
        print()

    def _create_pd_data(self):
        data = {}
        for tarifa in [x.desc for x in self.tarifak]:
            dd = []
            for ym in list(self.bills.keys()):
                bill = self.bills[ym][tarifa]
                dd.append(bill.get_mindosszesen())
            data[tarifa] = dd
        self.df = pd.DataFrame(data, index=list(self.bills.keys()))

    def print_table(self, df: DataFrame, desc="Cumulated costs"):
        dft = df.copy()
        dft = dft[sorted(dft.columns)]
        dft['_Átlag_'] = dft.mean(axis=1)
        print(dft.sort_values("_Átlag_"))
        print()

    def report(self):
        # for tarifa in self.tarifak:
        # print(tarifa)
        self.report_tarifa()

        dft = self.df.copy()
        self.print_table(dft)

        dft = self.df.copy()
        self.print_table(dft.T)


if __name__ == '__main__':
    print(json.dumps(Tarifa().__dict__, indent=4))

    input = "Report_2022-01-29_Sanyi"
    input = "Report_2020_Sanyi"
    input = "Report_all_Zita"

    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('--tarif_file', '-t',
                            help='A tarifákat tartalmazó file',
                            default='tarifak.json')
    arg_parser.add_argument('--call_records_file', '-c',
                            help='A híváslista file, amit a Callyzer generált',
                            default=f'./work/input/{input}.csv')
    args = arg_parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    billing = Billing(
        tarifak_file=args.tarif_file,
        call_records_file=args.call_records_file
    )
    billing.create_bills()
    billing.report()

    # xls = f'./work/output/{input}.xlsx'
    # print(f"\nSaving data to file {xls}")
    # excelWriter = pd.ExcelWriter(xls)
    # df.to_excel(excelWriter, index=True)
    # excelWriter.save()
