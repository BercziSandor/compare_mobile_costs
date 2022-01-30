import datetime
import json
import logging
import math
import sys
from typing import List

import pandas as pd
# https://pypi.org/project/phonenumbers/
import phonenumbers
from phonenumbers import carrier
from pytimeparse.timeparse import timeparse


def parseNumber(nr: str):
    nr = str(nr)
    # print("Parsing nr [{}]".format(nr))
    if nr.startswith('06'):
        nr = "+36" + nr[2:]
    if len(nr) == 11 and not nr.startswith("+"): nr = "+" + nr
    # Hordozott szám :(
    if nr == "+36301837880": nr = "+36201837880"
    if nr == 'nan': nr = "+36201837880"  # hidden number
    n = phonenumbers.parse(nr, region="HU")
    return n


class Tarifa:
    yearMonth = -1
    maradek_ingyen_percek = 0
    maradek_ingyen_percek_sajat = 0

    # last_cr_date = datetime.datetime.strptime("1970 01 01", "%Y %m %d")

    @staticmethod
    def load(fle: str):
        logging.info(f"Loading file {fle}...")
        with open(fle, encoding='utf8') as file:
            data = json.load(file)
        return [Tarifa(e) for e in data["tarifak"]]

    def __init__(self, params):
        # print("params: " + str(params))
        self.desc = params.get("desc", "")
        if params.get("carrier"):
            self.carrier = params["carrier"]
        else:
            raise Exception("Carrier not given for tarif {}".format(self.desc))

        self.base = params.get("base", 'perc')
        self.ingyen_percek = params.get("ingyen_percek", 0)
        self.alap_dij = int(params["alap_dij"])
        self.ingyen_percek_sajat = params.get("ingyen_percek_sajat", 0)
        self.perc_dij = int(params.get("perc_dij", 0))
        self.netGB = params["netGB"]
        self.yearMonth = params.get("yearMonth", -1)
        self.fizetendo = {}

    def __str__(self):
        r = f"Név:{self.desc},"
        r += f"Szolg:{self.carrier}\n"
        r += f"Alapdíj:{self.alap_dij}\n"
        r += f"Számlázás alapja:{self.base}\n"
        r += f"Ingyen percek:{self.ingyen_percek}\n"
        r += f"Ingyen percek hálózaton belül:{self.ingyen_percek_sajat}\n"
        r += f"Percdíj: {self.perc_dij} Ft\n"
        r += f"Mobilnet: {self.netGB}GB\n"
        r += f""
        return r


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

    def get_szamolt_dij(self, tarifa: Tarifa):
        logging.info(f"get_szamolt_dij({self}, {tarifa.carrier} - {tarifa.desc})")
        # if self.szamolt_dij is not None:
        #     logging.info("Már kiszámolva.")
        #     return self.szamolt_dij

        if tarifa.last_cr_date > self.start:
            raise Exception(
                "Error: nem időrendi sorrendben érkeznek be a rekordok, így nem lehet feldolgozni őket.\n{}".format(
                    self))
        tarifa.last_cr_date = self.start
        self.szamolt_dij = 0

        if tarifa.yearMonth != self.yearMonth:
            # print("*** Új hónap kezdődik! *** {} -> {}".format(tarifa.yearMonth, self.yearMonth))
            # if tarifa.yearMonth >0: print("Előző havi díj: {}".format(tarifa.fizetendo[str(tarifa.yearMonth)]))
            tarifa.yearMonth = self.yearMonth
            tarifa.fizetendo[str(tarifa.yearMonth)] = tarifa.alap_dij
            tarifa.maradek_ingyen_percek = tarifa.ingyen_percek
            tarifa.maradek_ingyen_percek_sajat = tarifa.ingyen_percek_sajat

        if self.type != 'Outgoing': return 0
        if self.hossz_perc == 0: return 0
        halozaton_belul = tarifa.carrier == self.toCarrier
        perc_dij = tarifa.perc_dij
        fizetendo_perc = self.hossz_perc

        if halozaton_belul:
            logging.info("Ez egy hálózaton belüli hívás.")
            if tarifa.maradek_ingyen_percek_sajat > 0:
                if fizetendo_perc <= tarifa.maradek_ingyen_percek_sajat:
                    # elég a keret
                    tarifa.maradek_ingyen_percek_sajat = tarifa.maradek_ingyen_percek_sajat - fizetendo_perc
                    fizetendo_perc = 0
                    logging.info(
                        "{} ingyen perc elhasználva, marad még {} ingyen perc saját hálózaton belül.".format(
                            self.hossz_perc, tarifa.maradek_ingyen_percek_sajat))
                else:
                    # nem elég a keret
                    fizetendo_perc = fizetendo_perc - tarifa.maradek_ingyen_percek_sajat
                    tarifa.maradek_ingyen_percek_sajat = 0
                    logging.info(
                        "{} ingyen perc elhasználva, viszont ezzel elfogyott a saját hálózaton belüli ingyen perc, sőt, még {} elszámolandó.".format(
                            1, 2))

        if fizetendo_perc > 0:
            if tarifa.maradek_ingyen_percek > 0:
                if fizetendo_perc <= tarifa.maradek_ingyen_percek:
                    tarifa.maradek_ingyen_percek = tarifa.maradek_ingyen_percek - fizetendo_perc
                    fizetendo_perc = 0
                    logging.info("Marad még {} ingyen perc".format(tarifa.maradek_ingyen_percek))
                else:
                    fizetendo_perc = fizetendo_perc - tarifa.maradek_ingyen_percek
                    tarifa.maradek_ingyen_percek = 0
                    logging.info("Ezzel elfogyott az ingyen perc, {} percet fizetni kell.".format(
                        fizetendo_perc))

        self.szamolt_dij = fizetendo_perc * perc_dij
        tarifa.fizetendo[str(tarifa.yearMonth)] += self.szamolt_dij
        return self.szamolt_dij


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


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING)

    tarifak = Tarifa.load("tarifak.json")
    input = "Report_all_Zita"
    input = "Report_2022-01-29_Sanyi"
    input = "Report_2020_Sanyi"

    call_records = CallRecord.load(f'./work/input/{input}.csv')

    bills = {}
    for tarifa in tarifak:
        for call_record in call_records:
            if call_record.yearMonth not in bills:
                bills[call_record.yearMonth] = {}

            if tarifa.desc not in bills[call_record.yearMonth]:
                bills[call_record.yearMonth][tarifa.desc]: Bill = Bill(tarifa=tarifa)
            b: Bill = bills[call_record.yearMonth][tarifa.desc]
            b.add_call_record(call_record)

    for yearMonth in bills:
        # print(f"{yearMonth}:")
        for tarifa in bills[yearMonth]:
            bill: Bill = bills[yearMonth][tarifa]
            # print(f" {tarifa}: {bill.get_mindosszesen()}")

    data = {}
    for tarifa in [x.desc for x in tarifak]:
        dd = []
        for ym in list(bills.keys()):
            bill = bills[ym][tarifa]
            dd.append(bill.get_mindosszesen())
        data[tarifa] = dd
    df = pd.DataFrame(data, index=list(bills.keys()))
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', None)

    print("Cumulated costs:")
    print(df)

    xls = f'./work/output/{input}.xlsx'
    print(f"\nSaving data to file {xls}")
    excelWriter = pd.ExcelWriter(xls)
    df.to_excel(excelWriter, index=True)
    excelWriter.save()
