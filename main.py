import argparse
import datetime
import json
import logging
import math
import os
import sys
from operator import itemgetter
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
        self.free_mins = params.get("ingyen_percek", 0)
        self.free_mins_net_intern = params.get("ingyen_percek_sajat", 0)
        self.ingyen_percek_eu = params.get("ingyen_percek_eu", None)

        self.perc_dij = int(params.get("perc_dij", 0))
        self.netGB = int(params.get("netGB", 0))

    def __str__(self):
        r = f"Név:{self.desc}\n"
        r += f"Szolg:{self.carrier}\n"
        r += f"Alapdíj:{self.alap_dij}\n"
        r += f"Számlázás alapja:{self.base}\n"
        r += f"Ingyen percek:{self.free_mins}\n"
        r += f"Ingyen percek hálózaton belül:{self.free_mins_net_intern}\n"
        r += f"Percdíj: {self.perc_dij} Ft\n"
        r += f"Mobilnet: {self.netGB}GB\n"
        r += f""
        return r

    def get_pandas_data(self, type: str = "") -> list:
        if type == 'header':
            retval = ['Szolgáltató', 'Alapdíj', 'Számlázás alapja', 'Ingyen percek',
                      'Ingyen percek hál. belül', 'Ingyen percek EU', 'Percdíj', 'Mobilnet[GB]']
        else:
            retval = [self.carrier, self.alap_dij, self.base, self.free_mins,
                      self.free_mins_net_intern, self.ingyen_percek_eu, self.perc_dij, self.netGB]
        return retval


class CallRecord:

    @staticmethod
    def load(fle: str):
        logging.info(f"Loading file {fle}...")
        lines = import_csv(fle)
        lines = sorted(lines, key=itemgetter('Date Time'))
        callRecords = [CallRecord(line) for line in lines]
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

        # 2021-01-22 17:49:10
        self.start = datetime.datetime.strptime(dict["Date Time"], "%Y-%m-%d %H:%M:%S")
        self.epoch = int(self.start.timestamp())
        self.yearMonth = self.start.strftime("%Y.%m")
        dur_sec = int(str(dict["Duration"]))
        self.end = self.start + datetime.timedelta(seconds=dur_sec)

        self.duration = self.end - self.start
        self.hossz_perc = math.ceil(self.duration.seconds / 60)
        self.szamolt_dij = None

    def __repr__(self):
        r = "{}, {} mins, ".format(self.start, self.hossz_perc)
        r += "direction: {},".format(self.type)
        r += "price: {} Ft,".format(self.szamolt_dij)
        return r


class Bill:
    def __init__(self, tarifa: Tarifa, callRecords: List[CallRecord] = []):
        self.details = {}
        self.tarifa = tarifa
        self.last_cr_date = None
        self.yearMonth = None
        self.callRecords = {}
        [self.add_call_record(x) for x in callRecords]

        self.remainig_free_mins = tarifa.free_mins
        self.remainig_free_mins_net_intern = tarifa.free_mins_net_intern
        self.recalculate_all()

    def add_call_record(self, callRecord: CallRecord, do_billing=True):
        if self.yearMonth is None:
            self.yearMonth = callRecord.yearMonth
        else:
            if self.yearMonth != callRecord.yearMonth:
                logging.error("This call shouldn't be here.")
                sys.exit(1)
        if callRecord.epoch in self.callRecords:
            logging.debug("Double call records for the same time???")
            # sys.exit(1)
            callRecord.epoch += 1
        self.callRecords[callRecord.epoch] = callRecord
        if do_billing: self.bill(callRecord)

    def bill(self, callRecord: CallRecord):
        logging.info(f"bill({callRecord}, {self.tarifa.carrier} - {self.tarifa.desc})")
        cid = callRecord.id
        if cid in self.details:
            logging.info("Already calculated.")
            return self.details[callRecord.id]['fizetendo']

        self.details[cid] = {}
        self.details[cid]['fizetendo'] = 0

        if self.last_cr_date is not None and self.last_cr_date > callRecord.start:
            raise Exception(
                "Error: The call records should be sorted by date, "
                "they aren't.\n{}".format(
                    callRecord))
        self.last_cr_date = callRecord.start

        if callRecord.type.lower() != 'outgoing': return 0
        if callRecord.hossz_perc == 0: return 0

        is_net_intern = self.tarifa.carrier == callRecord.toCarrier
        price_per_min = self.tarifa.perc_dij
        mins_to_pay = callRecord.hossz_perc

        if is_net_intern:
            logging.info("This is a network-intern call.")
            if self.remainig_free_mins_net_intern > 0:
                if mins_to_pay <= self.remainig_free_mins_net_intern:
                    # elég a keret
                    self.remainig_free_mins_net_intern = \
                        self.remainig_free_mins_net_intern \
                        - \
                        mins_to_pay
                    mins_to_pay = 0
                    logging.info(
                        f"Already consumed {callRecord.hossz_perc} network-intern free mins, "
                        f"remaining {self.remainig_free_mins_net_intern} mins.")
                else:
                    # nem elég a keret
                    mins_to_pay = mins_to_pay - self.remainig_free_mins_net_intern
                    self.remainig_free_mins_net_intern = 0
                    logging.info(
                        "{} ingyen perc elhasználva, viszont ezzel elfogyott a saját hálózaton belüli ingyen perc, sőt, még {} elszámolandó.".format(
                            1, 2))

        if mins_to_pay > 0:
            if self.maradek_ingyen_percek > 0:
                if mins_to_pay <= self.maradek_ingyen_percek:
                    self.maradek_ingyen_percek = self.maradek_ingyen_percek - \
                                                 mins_to_pay
                    mins_to_pay = 0
                    logging.info(
                        "Marad még {} ingyen perc".format(self.maradek_ingyen_percek))
                else:
                    mins_to_pay = mins_to_pay - self.maradek_ingyen_percek
                    self.maradek_ingyen_percek = 0
                    logging.info(
                        "Ezzel elfogyott az ingyen perc, {} percet fizetni kell.".format(
                            mins_to_pay))

        self.details[cid]['fizetendo_perc'] = mins_to_pay
        self.details[cid]['percdij'] = price_per_min
        self.details[cid]['fizetendo'] = mins_to_pay * price_per_min

        return self.details[cid]['fizetendo']

    def recalculate_all(self):
        for callRecord in self.callRecords:
            self.bill(callRecord)

    def get_endsum(self):
        endsum = 0
        endsum += self.tarifa.alap_dij
        for detail in self.details.values():
            if 'fizetendo' in detail: endsum += detail['fizetendo']
        self.endsum = endsum
        return endsum


def import_csv(fle: str):
    return pd.read_csv(fle, dtype=str, delimiter=',').to_dict('records')


class Billing:
    def __init__(self, tariff_file: str, call_records_file: str):
        self.tarifak = Tarifa.load(tariff_file)
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
                bill.get_endsum()

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
                dd.append(bill.get_endsum())
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
    input = "Z Report 2020"
    input = "CallyzerBackup_2022-03-20_10_02_04"

    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('--tariff_file', '-t',
                            help='The JSON file containing the tariffs.',
                            default='tariffs.json')
    arg_parser.add_argument('--call_records_file', '-c',
                            help='The callrecord file generated by '
                                 'Callyzer',
                            default=f'./work/input/{input}.csv')
    args = arg_parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    if not os.path.exists(args.tariff_file):
        raise FileExistsError(
            f"File {args.tarif_file} does not exist, aborting.")
        sys.exit(0)

    if not os.path.exists(args.call_records_file):
        raise FileExistsError(
            f"File {args.call_records_file} does not exist, aborting.")
        sys.exit(0)

    billing = Billing(
        tariff_file=args.tariff_file,
        call_records_file=args.call_records_file
    )
    billing.create_bills()
    billing.report()

    # xls = f'./work/output/{input}.xlsx'
    # print(f"\nSaving data to file {xls}")
    # excelWriter = pd.ExcelWriter(xls)
    # df.to_excel(excelWriter, index=True)
    # excelWriter.save()
