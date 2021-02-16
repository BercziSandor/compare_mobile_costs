import datetime
import json
import math
import pandas as pd

# https://pypi.org/project/phonenumbers/
import phonenumbers
from phonenumbers import carrier
from pytimeparse.timeparse import timeparse


def parseNumber(nr: str):
    nr = str(nr)
    # print("Parsing nr [{}]".format(nr))
    if len(nr) == 9: nr = str("+36{}".format(nr))
    if len(nr) == 11: nr = str("+{}".format(nr))
    # Hordozott szám :(
    if nr == "+36301837880": nr = "+36201837880"
    if nr == 'nan': nr = "+36201837880"  # hidden number
    return phonenumbers.parse(nr, "HU")


class Tarifa:
    yearMonth = -1
    maradek_ingyen_percek = 0
    maradek_ingyen_percek_sajat = 0
    last_cr_date = datetime.datetime.strptime("1970 01 01", "%Y %m %d")

    @staticmethod
    def load(fle: str):
        print (f"Loading file {fle}...")
        with open(fle, encoding='utf8') as file:
            data = json.load(file)
        return [Tarifa(e) for e in data["tarifak"]]

    def __init__(self, kwargs):
        # print("kwargs: " + str(kwargs))
        self.desc = kwargs.get("desc", "")
        if kwargs.get("carrier"):
            self.carrier = kwargs["carrier"]
        else:
            raise Exception("Carrier not given for tarif {}".format(self.desc))

        self.base = kwargs.get("base", 'perc')
        self.ingyen_percek = kwargs.get("ingyen_percek", 0)
        self.alap_dij = int(kwargs["alap_dij"])
        self.ingyen_percek_sajat = kwargs.get("ingyen_percek_sajat", 0)
        self.perc_dij = int(kwargs.get("perc_dij", 0))
        self.netGB = kwargs["netGB"]
        self.yearMonth = kwargs.get("yearMonth", -1)
        self.fizetendo = {}

    def __str__(self):
        r = f"Név:                           {self.desc}\n"
        r += f"Szolg:                         {self.carrier}\n"
        r += f"Alapdíj:                       {self.alap_dij}\n"
        r += f"Számlázás alapja:              {self.base}\n"
        r += f"Ingyen percek:                 {self.ingyen_percek}\n"
        r += f"Ingyen percek hálózaton belül: {self.ingyen_percek_sajat}\n"
        r += f"Percdíj:                       {self.perc_dij} Ft\n"
        r += f"Mobilnet:                      {self.netGB}GB\n"
        r += f""
        return r


class CallRecord:

    @staticmethod
    def load(fle: str):
        print (f"Loading file {fle}...")
        return [CallRecord(line) for line in reversed(import_csv(fle))]

    def __init__(self, dict):
        self.fromName = dict["Name"]
        self.type = dict["Type"]
        self.toNumber = parseNumber(dict["To Number"])
        self.toCarrier = carrier.name_for_number(self.toNumber, "hu")

        f = "{} {}".format(dict["Date"], dict["Time"])
        self.start = datetime.datetime.strptime(f, "%Y-%m-%d %I:%M %p")
        self.yearMonth = int(self.start.strftime("%Y%m"))
        self.end = self.start + datetime.timedelta(0, timeparse(str(dict["Duration"])))
        self.duration = self.end - self.start
        self.hossz_perc = math.ceil(self.duration.seconds / 60)
        self.szamolt_dij = None

    def __repr__(self):
        r = "{} (duration: {}: {} mins)".format(self.start,
                                                str(self.duration),
                                                self.hossz_perc
                                                )
        r += " - type: {}".format(self.type)
        return r

    def get_szamolt_dij(self, szerzodes: Tarifa):
        if szerzodes.last_cr_date > cr.start:
            raise Exception(
                "Error: nem időrendi sorrendben érkeznek be a rekordok, így nem lehet feldolgozni őket.\n{}".format(
                    self))
        szerzodes.last_cr_date = cr.start
        self.szamolt_dij = 0

        if szerzodes.yearMonth != self.yearMonth:
            # print("*** Új hónap kezdődik! *** {} -> {}".format(szerzodes.yearMonth, self.yearMonth))
            # if szerzodes.yearMonth >0: print("Előző havi díj: {}".format(szerzodes.fizetendo[str(szerzodes.yearMonth)]))
            szerzodes.yearMonth = self.yearMonth
            szerzodes.fizetendo[str(szerzodes.yearMonth)] = szerzodes.alap_dij
            szerzodes.maradek_ingyen_percek = szerzodes.ingyen_percek
            szerzodes.maradek_ingyen_percek_sajat = szerzodes.ingyen_percek_sajat

        if self.type != 'Outgoing': return 0
        if self.hossz_perc == 0: return 0
        halozaton_belul = szerzodes.carrier == self.toCarrier
        perc_dij = szerzodes.perc_dij
        fizetendo_perc = self.hossz_perc

        if halozaton_belul:
            if szerzodes.maradek_ingyen_percek_sajat > 0:
                if fizetendo_perc <= szerzodes.maradek_ingyen_percek_sajat:
                    # elég a keret
                    szerzodes.maradek_ingyen_percek_sajat = szerzodes.maradek_ingyen_percek_sajat - fizetendo_perc
                    fizetendo_perc = 0
                    # print("{} ingyen perc elhasználva, marad még {} ingyen perc saját hálózaton belül.".format(self.hossz_perc, szerzodes.maradek_ingyen_percek_sajat))
                else:
                    # nem elég a keret
                    fizetendo_perc = fizetendo_perc - szerzodes.maradek_ingyen_percek_sajat
                    szerzodes.maradek_ingyen_percek_sajat = 0
                    # print("{} ingyen perc elhasználva, viszont ezzel elfogyott a saját hálózaton belüli ingyen perc, sőt, még {} elszámolandó.".format(1, 2))

        if fizetendo_perc > 0:
            if szerzodes.maradek_ingyen_percek > 0:
                if fizetendo_perc <= szerzodes.maradek_ingyen_percek:
                    szerzodes.maradek_ingyen_percek = szerzodes.maradek_ingyen_percek - fizetendo_perc
                    fizetendo_perc = 0
                    # print("Marad még {} ingyen perc".format(szerzodes.maradek_ingyen_percek))
                else:
                    fizetendo_perc = fizetendo_perc - szerzodes.maradek_ingyen_percek
                    szerzodes.maradek_ingyen_percek = 0
                    # print("Ezzel elfogyott az ingyen perc, {} percet fizetni kell.".format(fizetendo_perc))

        self.szamolt_dij = fizetendo_perc * perc_dij
        szerzodes.fizetendo[str(szerzodes.yearMonth)] += self.szamolt_dij
        return self.szamolt_dij


def import_csv(fle: str):
    # return [tuple(x) for x in df.values]
    # return [[row[col] for col in df.columns] for row in df.to_dict('records')]
    return pd.read_csv(fle, delimiter=',').to_dict('records')


if __name__ == '__main__':
    tarifak = Tarifa.load("tarifak.json")
    input = "Report_2020_Sanyi"
    call_records = CallRecord.load(f'./work/input/{input}.csv')

    print("\nCalculating costs:")
    for tarifa in tarifak:
        # print("\n********************************\nSzerződés: {}({})".format(tarifa.desc, tarifa.carrier))
        print(f" - {tarifa.desc}")
        for cr in call_records:
            # print("\n {}: {} call, len: {} min {}->{}".format(cr.start.strftime('%m.%d %H:%M'), cr.type, cr.hossz_perc, tarifa.carrier, cr.toCarrier))
            cr.get_szamolt_dij(tarifa)
            # print("  Díj: {} Ft".format(cr.szamolt_dij))
    print()

    # yms=tarifak[0].fizetendo.keys()

    data = {}
    for tarifa in tarifak:
        data[tarifa.desc] = list(tarifa.fizetendo.values())
    df = pd.DataFrame(data, index=list(tarifak[0].fizetendo.keys()))

    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', None)
    print("Cumulated costs:")
    print(df)

    xls=f'./work/output/{input}.xlsx'
    print(f"\nSaving data to file {xls}")
    excelWriter = pd.ExcelWriter(xls)
    df.to_excel(excelWriter, index=True)
    excelWriter.save()
