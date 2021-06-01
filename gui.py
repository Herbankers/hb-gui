from PyQt6 import QtCore, QtGui, QtWidgets, uic
from PyQt6.QtCore import *
import functools
import getopt
import sys

from hbp import *
from ui.main import *

#
# On PC keyboards,
#   '-' can be used instead of '*'
#  and
#   '=' can be used instead of '#'
#


#
# TODO
# Client side countdown to automatically end session after hbp.HBP_TIMEOUT seconds
#

app = None      # QApplication
hbp = None      # hbp object
arduino = None  # serial object

# although both the server and HBP support PINs of up to 12 numbers, we've decided to hardcode 4 in the client for now
# for convenience sake
PIN_LENGTH = 4

class Arduino(QObject):
    keyPress = pyqtSignal(str)
    cardScan = pyqtSignal(str)

    def run(self):
        while True:
            data = arduino.readline()[:-2]
            decoded_data = str(data, 'utf-8')

            if decoded_data[0:1] == 'K':
                self.keyPress.emit(decoded_data[1:])
            if decoded_data[0:1] == 'U':
                self.cardScan.emit(decoded_data[1:])

class MainWindow(QtWidgets.QMainWindow):
    CARD_PAGE = 0
    LOGIN_PAGE = 1
    MAIN_PAGE = 2
    WITHDRAW_PAGE = 3
    WITHDRAW_MANUAL_PAGE = 4
    WITHDRAW_BILLS_PAGE = 5
    DONATE_PAGE = 6
    BALANCE_PAGE = 7
    RESULT_PAGE = 8

    MONOSPACE_HTML = '<font face="Fira Mono, DejaVu Sans Mono, Menlo, Consolas, Liberation Mono, Monaco, Lucida Console, monospace">'

    card_id = ''
    iban = ''
    keybuf = []
    keyindex = 0
    counter5 = 0
    counter10 = 0
    counter50 = 0

    translator = QTranslator()

    def __init__(self, parent = None):
        super().__init__(parent)
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.ui.stack.setCurrentIndex(self.CARD_PAGE)

        # create a thread for serial connections if an arduino is connected
        if arduino != None:
            self.thread = QThread()
            self.worker = Arduino()
            self.worker.moveToThread(self.thread)

            self.thread.started.connect(self.worker.run)
            self.worker.keyPress.connect(self.keypadPress)
            self.worker.cardScan.connect(self.cardScan)

            self.thread.start()

        self.fullScrSc = QtGui.QShortcut(QtGui.QKeySequence.StandardKey.FullScreen, self)
        self.fullScrSc.activated.connect(lambda: self.showNormal() if self.isFullScreen() else self.showFullScreen())

        # Card page
        self.card_menu = {
            '1': self.dutch, '2': self.german, '3': self.english
        }
        self.ui.dutch.clicked.connect(self.card_menu['1'])
        self.ui.german.clicked.connect(self.card_menu['2'])
        self.ui.english.clicked.connect(self.card_menu['3'])

        self.login_menu = {
            '*': self.clearInput
        }
        self.ui.loginAbort.clicked.connect(self.login_menu['*'])

        # Main page
        self.main_menu = {
            '1': self.withdrawPage,
            '4': self.donatePage,   '6': functools.partial(self.withdraw, amount=7000),
            '7': self.balancePage,
                                    '#': functools.partial(self.showResult, text=self.tr('Nog een fijne dag!'))
        }
        self.ui.withdraw.clicked.connect(self.main_menu['1'])
        self.ui.donate.clicked.connect(self.main_menu['4'])
        self.ui.balance.clicked.connect(self.main_menu['7'])
        self.ui.quickWithdrawal.clicked.connect(self.main_menu['6'])
        self.ui.logout.clicked.connect(self.main_menu['#'])

        # Withdraw page
        self.withdraw_menu = {
            '1': functools.partial(self.withdrawBillsPage, amount =500), '3': functools.partial(self.withdrawBillsPage, amount=5000),
            '4': functools.partial(self.withdrawBillsPage, amount=1000), '6': functools.partial(self.withdrawBillsPage, amount=10000),
            '*': self.abort,                                    '#': self.withdrawManualPage
        }
        self.ui.withdrawOption0.clicked.connect(self.withdraw_menu['1'])
        self.ui.withdrawOption1.clicked.connect(self.withdraw_menu['4'])
        self.ui.withdrawOption2.clicked.connect(self.withdraw_menu['3'])
        self.ui.withdrawOption3.clicked.connect(self.withdraw_menu['6'])
        self.ui.withdrawAbort.clicked.connect(self.withdraw_menu['*'])
        self.ui.withdrawManual.clicked.connect(self.withdraw_menu['#'])

        # Withdraw manual page
        self.withdrawManual_menu = {
            '*': self.clearInput, '#': self.withdrawFromKeybuf
        }
        self.ui.withdrawManualAbort.clicked.connect(self.withdrawManual_menu['*'])
        self.ui.withdrawManualAccept.clicked.connect(self.withdrawManual_menu['#'])

        # Withdraw bill selection page
        self.withdrawBills_menu = {
            '*': self.abort, '#': functools.partial(self.withdraw, amount = 1000),
            '1': self.select1, '2': self.deselect1,
            '3': self.select2, '4': self.deselect2,
            '5': self.select3, '6': self.deselect3
        }

        self.ui.withdrawBillsAbort.clicked.connect(self.withdrawBills_menu['*'])
        self.ui.withdrawBillsAccept.clicked.connect(self.withdrawBills_menu['#'])

        # Donate page
        self.donate_menu = {
            '*': self.clearInput, '#': self.donate
        }
        self.ui.donateAbort.clicked.connect(self.donate_menu['*'])
        self.ui.donateAccept.clicked.connect(self.donate_menu['#'])

        # Balance page
        self.balance_menu = {
            '#': self.abort
        }
        self.ui.balanceAccept.clicked.connect(self.balance_menu['#'])

        self.menus = {
            self.CARD_PAGE: self.card_menu,
            self.LOGIN_PAGE: self.login_menu,
            self.MAIN_PAGE: self.main_menu,
            self.WITHDRAW_PAGE: self.withdraw_menu,
            self.WITHDRAW_MANUAL_PAGE: self.withdrawManual_menu,
            self.WITHDRAW_BILLS_PAGE: self.withdrawBills_menu,
            self.DONATE_PAGE: self.donate_menu,
            self.BALANCE_PAGE: self.balance_menu
        }

    # card scan handler
    @pyqtSlot(str)
    def cardScan(self, data):
        if self.ui.stack.currentIndex() == self.CARD_PAGE:
            self.card_id = data
            self.iban = 'NL35HERB2932749274' # FIXME correctly retrieve iban from rfid card

            self.ui.pinText.setGraphicsEffect(None)
            self.ui.loginAbort.setGraphicsEffect(None)
            self.ui.stack.setCurrentIndex(self.LOGIN_PAGE)
            self.clearInput(abort=False)

    def keyHandler(self, key):
        page = self.ui.stack.currentIndex()

        try:
            self.menus[page][key]()
            return
        except KeyError:
            pass

        # XXX Temporary XXX
        if page == self.CARD_PAGE:
            if key == '*':
                self.card_id = 'EBA8001B'
                self.iban = 'NL35HERB2932749274'

                self.ui.pinText.setGraphicsEffect(None)
                self.ui.loginAbort.setGraphicsEffect(None)
                self.ui.stack.setCurrentIndex(self.LOGIN_PAGE)
                self.clearInput(abort=False)
                return
        elif page == self.LOGIN_PAGE:
            # store the key in the keybuffer
            self.keybuf.append(key)

            # change the abort button to a correction button
            self.ui.loginAbort.setText(self.tr('﹡    Correctie'))

            # update the pin dots on the display
            if self.keyindex == 0:
                self.ui.pin.setText('•   ')
            elif self.keyindex == 1:
                self.ui.pin.setText('••  ')
            elif self.keyindex == 2:
                self.ui.pin.setText('••• ')
            elif self.keyindex == 3:
                self.ui.pin.setText('••••')

            self.keyindex += 1
            if self.keyindex < PIN_LENGTH or self.keyindex > PIN_LENGTH:
                return

            # animate the fading of the loginAbort button
            self.loginAbortEff = QtWidgets.QGraphicsOpacityEffect()
            self.loginAbortEff.setOpacity(0.0)
            self.ui.loginAbort.setGraphicsEffect(self.loginAbortEff)

            # animate the fading of the pin entry help text
            self.pinTextEff = QtWidgets.QGraphicsOpacityEffect()
            self.ui.pinText.setGraphicsEffect(self.pinTextEff)
            self.pinTextAnim = QPropertyAnimation(self.pinTextEff, b"opacity")
            self.pinTextAnim.setStartValue(1.0)
            self.pinTextAnim.setEndValue(0.0)
            self.pinTextAnim.setDuration(300)
            self.pinTextAnim.start(self.pinTextAnim.DeletionPolicy.DeleteWhenStopped)

            # animate the translation of the pin dots to the center of the screen
            self.pinAnim = QPropertyAnimation(self.ui.pin, b"pos")
            self.pinAnim.setEndValue(QPoint(self.ui.pin.x(), self.ui.pin.y() - int(self.ui.pinText.height() / 2)))
            self.pinAnim.setDuration(300)
            self.pinAnim.start(self.pinTextAnim.DeletionPolicy.DeleteWhenStopped)

            # short delay here to show that the 4th character has been entered
            self.timer = QTimer()
            self.timer.timeout.connect(self.login)
            self.timer.setSingleShot(True)
            self.timer.start(700)
        elif page in (self.WITHDRAW_MANUAL_PAGE, self.DONATE_PAGE):
            # store the keyboard key in the keybuffer
            if self.keyindex > 2:
                return
            self.keybuf[self.keyindex] = key
            self.keyindex += 1

            if self.ui.stack.currentIndex() == self.WITHDRAW_MANUAL_PAGE:
                # change the abort button to a correction button
                self.ui.withdrawManualAbort.setText(self.tr('﹡    Correctie'))

                # show the accept button
                self.ui.withdrawManualAccept.show()

                # write the updated amount to the display
                self.ui.withdrawAmount.setText(self.MONOSPACE_HTML + ''.join(self.keybuf).replace(' ', '&nbsp;') + '</font> EUR')
            else:
                # change the abort button to a correction button
                self.ui.donateAbort.setText(self.tr('﹡    Correctie'))

                # show the accept button
                self.ui.donateAccept.show()

                # write the updated amount to the display
                self.ui.donateAmount.setText(self.MONOSPACE_HTML + ''.join(self.keybuf).replace(' ', '&nbsp;') + '</font> EUR')

    # keypad input handler
    @pyqtSlot(str)
    def keypadPress(self, data):
        self.keyHandler(data)

    # resolve the keyboard key event code to a character (only numbers are accepted)
    def getKeyFromEvent(self, key):
        if key == Qt.Key.Key_0:
            return '0'
        elif key == Qt.Key.Key_1:
            return '1'
        elif key == Qt.Key.Key_2:
            return '2'
        elif key == Qt.Key.Key_3:
            return '3'
        elif key == Qt.Key.Key_4:
            return '4'
        elif key == Qt.Key.Key_5:
            return '5'
        elif key == Qt.Key.Key_6:
            return '6'
        elif key == Qt.Key.Key_7:
            return '7'
        elif key == Qt.Key.Key_8:
            return '8'
        elif key == Qt.Key.Key_9:
            return '9'
        elif key == Qt.Key.Key_Minus:
            return '*'
        elif key == Qt.Key.Key_Equal:
            return '#'
        else:
            return None

    # keyboard input handler
    def keyPressEvent(self, event):
        key = self.getKeyFromEvent(event.key())
        if key == None:
            return

        self.keyHandler(key)

    # either clear input from the key buffer or abort if the buffer is empty
    @pyqtSlot()
    def clearInput(self, abort=True):
        if self.ui.stack.currentIndex() == self.LOGIN_PAGE:
            if not abort or self.keyindex > 0:
                self.keybuf = []

                # change the correction button back to an abort button
                self.ui.loginAbort.setText(self.tr('﹡    Afbreken'))

                # clear the display
                self.ui.pin.setText('')
            else:
                self.goHome()
        elif self.ui.stack.currentIndex() == self.WITHDRAW_MANUAL_PAGE:
            if not abort or self.keyindex > 0:
                self.keybuf = [' '] * 3

                # change the correction button back to an abort button
                self.ui.withdrawManualAbort.setText(self.tr('﹡    Afbreken'))

                # hide the accept button for now
                self.ui.withdrawManualAccept.hide()

                # clear the display
                self.ui.withdrawAmount.setText(self.MONOSPACE_HTML + '&nbsp;&nbsp;&nbsp;</font> EUR')
            else:
                self.abort()
        elif self.ui.stack.currentIndex() == self.DONATE_PAGE:
            if not abort or self.keyindex > 0:
                self.keybuf = [' '] * 3

                # change the correction button back to an abort button
                self.ui.donateAbort.setText(self.tr('﹡    Afbreken'))

                # hide the accept button for now
                self.ui.donateAccept.hide()

                # clear the display
                self.ui.donateAmount.setText(self.MONOSPACE_HTML + '&nbsp;&nbsp;&nbsp;</font> EUR')
            else:
                self.abort()

        self.keyindex = 0

    @pyqtSlot()
    def login(self):
        # TODO run on separate thread
        reply = hbp.login(self.card_id, self.iban, ''.join(self.keybuf))

        self.clearInput(abort=False)

        if reply == hbp.HBP_LOGIN_GRANTED:
            self.ui.stack.setCurrentIndex(self.MAIN_PAGE)

            name = hbp.info()
            if type(name) is list:
                self.ui.name.setText(self.tr('Welkom') + f' {name[0]} {name[1]}!')
            else:
                self.ui.name.setText(self.tr('Welkom!'))
        elif reply == hbp.HBP_LOGIN_DENIED:
            self.showResult(self.tr('Onjuiste PIN'), logout=False)
        elif reply == hbp.HBP_LOGIN_BLOCKED:
            self.showResult(self.tr('Deze kaart is geblokkeerd'), logout=False)
        else:
            self.showResult(self.tr('Een interne fout is opgetreden'), logout=False)
            print(reply)

    # FIXME replace these with lambda or something?
    @pyqtSlot()
    def abort(self):
        self.ui.stack.setCurrentIndex(self.MAIN_PAGE)
        self.counter5 = 0
        self.counter10 = 0
        self.counter50 = 0

    @pyqtSlot()
    def goHome(self):
        self.ui.stack.setCurrentIndex(self.CARD_PAGE)

    @pyqtSlot()
    def showResult(self, text, logout=True):
        self.ui.stack.setCurrentIndex(self.RESULT_PAGE)
        self.ui.resultText.setText(text)

        # automatically logout after 2 seconds
        self.timer = QTimer()
        if logout:
            self.timer.timeout.connect(self.logout)
        else:
            self.timer.timeout.connect(self.goHome)

        self.timer.setSingleShot(True)
        self.timer.start(2000)


    #
    # Card page
    #
    @pyqtSlot()
    def dutch(self):
        app.removeTranslator(self.translator)
        self.ui.retranslateUi(self)

    @pyqtSlot()
    def german(self):
        app.removeTranslator(self.translator)
        self.translator.load("ts/de_DE.qm")
        app.installTranslator(self.translator)
        self.ui.retranslateUi(self)

    @pyqtSlot()
    def english(self):
        app.removeTranslator(self.translator)
        self.translator.load("ts/en_US.qm")
        app.installTranslator(self.translator)
        self.ui.retranslateUi(self)


    #
    # Main page
    #
    @pyqtSlot()
    def withdrawPage(self):
        self.ui.stack.setCurrentIndex(self.WITHDRAW_PAGE)

    @pyqtSlot()
    def donatePage(self):
        self.ui.stack.setCurrentIndex(self.DONATE_PAGE)

        self.clearInput(abort=False)

    @pyqtSlot()
    def balancePage(self):
        self.ui.balanceAmount.setText(hbp.balance().replace('.', ',') + ' EUR')
        self.ui.stack.setCurrentIndex(self.BALANCE_PAGE)

    @pyqtSlot()
    def logout(self, doServerLogout=True):
        # we can check the reply, but this is really not needed, as it basically always succeeds
        if doServerLogout:
            hbp.logout()

        # we should clear all modified variables and labels here for security
        self.keybuf = []
        self.keyindex = 0
        self.counter5 = 0
        self.counter10 = 0
        self.counter50 = 0
        self.ui.withdrawAmount.setText('')
        self.ui.donateAmount.setText('')
        self.ui.balanceAmount.setText('')

        self.dutch()
        self.ui.stack.setCurrentIndex(self.CARD_PAGE)

    #
    # Withdraw page
    #
    @pyqtSlot()
    def withdraw(self, amount):
        # start processing
        self.ui.stack.setCurrentIndex(self.RESULT_PAGE)
        self.ui.resultText.setText(self.tr('Een moment geduld...'))
        reply = hbp.transfer('', amount);

        if reply in (hbp.HBP_TRANSFER_SUCCESS, hbp.HBP_TRANSFER_PROCESSING):
            # TODO operate money dispenser here (on a separate thread ofc)

            self.timer = QTimer()
            self.timer.timeout.connect(functools.partial(self.showResult, text=self.tr('Nog een fijne dag!')))
            self.timer.setSingleShot(True)
            self.timer.start(3000)
        elif reply == hbp.HBP_TRANSFER_INSUFFICIENT_FUNDS:
            self.ui.resultText.setText(self.tr('Uw saldo is ontoereikend'))

            self.timer = QTimer()
            self.timer.timeout.connect(self.abort)
            self.timer.setSingleShot(True)
            self.timer.start(3000)
        elif reply == hbp.HBP_REP_TERMINATED:
            # server side session has expired
            self.logout(doServerLogout=False)
        else:
            self.showResult(self.tr('Een interne fout is opgetreden'))
            print(reply)

    #
    # Withdraw manual page
    #
    @pyqtSlot()
    def withdrawManualPage(self):
        self.ui.stack.setCurrentIndex(self.WITHDRAW_MANUAL_PAGE)

        self.clearInput(abort=False)

    @pyqtSlot()
    def withdrawFromKeybuf(self):
        try:
            amount = int(''.join(self.keybuf).replace(' ', '')) * 100
        except ValueError:
            # nothing has been entered yet
            return

        self.withdrawBillsPage(amount) #withdraw(amount)

    #
    # Withdraw bill selection page
    #
    @pyqtSlot()
    def withdrawBillsPage(self,amount):
        self.ui.stack.setCurrentIndex(self.WITHDRAW_BILLS_PAGE)
        if amount < 500:
            self.ui.fiveEuroText.setStyleSheet("text-decoration: line-through;color: rgb(160, 160, 160)")
            self.ui.amountBillsFive.setStyleSheet("text-decoration: line-through;color: rgb(160, 160, 160)")
            self.ui.btnPlusFive.setEnabled(False)
            self.ui.btnPlusFive.setStyleSheet("text-decoration: line-through;color: rgb(160, 160, 160);")
            self.ui.btnMinFive.setEnabled(False)
            self.ui.btnMinFive.setStyleSheet("text-decoration: line-through;color: rgb(160, 160, 160);")
            self.ui.tenEuroText.setStyleSheet("text-decoration: line-through;color: rgb(160, 160, 160)")
            self.ui.amountBillsTen.setStyleSheet("text-decoration: line-through;color: rgb(160, 160, 160)")
            self.ui.btnPlusTen.setEnabled(False)
            self.ui.btnPlusTen.setStyleSheet("text-decoration: line-through;color: rgb(160, 160, 160);")
            self.ui.btnMinTen.setEnabled(False)
            self.ui.btnMinTen.setStyleSheet("text-decoration: line-through;color: rgb(160, 160, 160);")
            self.ui.fifthyEuroText.setStyleSheet("text-decoration: line-through;color: rgb(160, 160, 160)")
            self.ui.amountBillsFifthy.setStyleSheet("text-decoration: line-through;color: rgb(160, 160, 160)")
            self.ui.btnPlusFifthy.setEnabled(False)
            self.ui.btnPlusFifthy.setStyleSheet("text-decoration: line-through;color: rgb(160, 160, 160);")
            self.ui.btnMinFifthy.setEnabled(False)
            self.ui.btnMinFifthy.setStyleSheet("text-decoration: line-through;color: rgb(160, 160, 160);")
        if amount == 500:
            self.ui.fiveEuroText.setStyleSheet(None)
            self.ui.amountBillsFive.setStyleSheet(None)
            self.ui.btnPlusFive.setEnabled(True)
            self.ui.btnPlusFive.setStyleSheet(None)
            self.ui.btnMinFive.setEnabled(True)
            self.ui.btnMinFive.setStyleSheet(None)
            self.ui.tenEuroText.setStyleSheet("text-decoration: line-through;color: rgb(160, 160, 160)")
            self.ui.amountBillsTen.setStyleSheet("text-decoration: line-through;color: rgb(160, 160, 160)")
            self.ui.btnPlusTen.setEnabled(False)
            self.ui.btnPlusTen.setStyleSheet("text-decoration: line-through;color: rgb(160, 160, 160);")
            self.ui.btnMinTen.setEnabled(False)
            self.ui.btnMinTen.setStyleSheet("text-decoration: line-through;color: rgb(160, 160, 160);")
            self.ui.fifthyEuroText.setStyleSheet("text-decoration: line-through;color: rgb(160, 160, 160)")
            self.ui.amountBillsFifthy.setStyleSheet("text-decoration: line-through;color: rgb(160, 160, 160)")
            self.ui.btnPlusFifthy.setEnabled(False)
            self.ui.btnPlusFifthy.setStyleSheet("text-decoration: line-through;color: rgb(160, 160, 160);")
            self.ui.btnMinFifthy.setEnabled(False)
            self.ui.btnMinFifthy.setStyleSheet("text-decoration: line-through;color: rgb(160, 160, 160);")
        if amount > 500 and amount < 5000:
            self.ui.fiveEuroText.setStyleSheet(None)
            self.ui.amountBillsFive.setStyleSheet(None)
            self.ui.btnPlusFive.setEnabled(True)
            self.ui.btnPlusFive.setStyleSheet(None)
            self.ui.btnMinFive.setEnabled(True)
            self.ui.btnMinFive.setStyleSheet(None)
            self.ui.tenEuroText.setStyleSheet(None)
            self.ui.amountBillsTen.setStyleSheet(None)
            self.ui.btnPlusTen.setEnabled(True)
            self.ui.btnPlusTen.setStyleSheet(None)
            self.ui.btnMinTen.setEnabled(True)
            self.ui.btnMinTen.setStyleSheet(None)
            self.ui.fifthyEuroText.setStyleSheet("text-decoration: line-through;color: rgb(160, 160, 160)")
            self.ui.amountBillsFifthy.setStyleSheet("text-decoration: line-through;color: rgb(160, 160, 160)")
            self.ui.btnPlusFifthy.setEnabled(False)
            self.ui.btnPlusFifthy.setStyleSheet("text-decoration: line-through;color: rgb(160, 160, 160);")
            self.ui.btnMinFifthy.setEnabled(False)
            self.ui.btnMinFifthy.setStyleSheet("text-decoration: line-through;color: rgb(160, 160, 160);")
        if amount >= 5000:
            self.ui.fiveEuroText.setStyleSheet(None)
            self.ui.amountBillsFive.setStyleSheet(None)
            self.ui.btnPlusFive.setEnabled(True)
            self.ui.btnPlusFive.setStyleSheet(None)
            self.ui.btnMinFive.setEnabled(True)
            self.ui.btnMinFive.setStyleSheet(None)
            self.ui.tenEuroText.setStyleSheet(None)
            self.ui.amountBillsTen.setStyleSheet(None)
            self.ui.btnPlusTen.setEnabled(True)
            self.ui.btnPlusTen.setStyleSheet(None)
            self.ui.btnMinTen.setEnabled(True)
            self.ui.btnMinTen.setStyleSheet(None)
            self.ui.fifthyEuroText.setStyleSheet(None)
            self.ui.amountBillsFifthy.setStyleSheet(None)
            self.ui.btnPlusFifthy.setEnabled(True)
            self.ui.btnPlusFifthy.setStyleSheet(None)
            self.ui.btnMinFifthy.setEnabled(True)
            self.ui.btnMinFifthy.setStyleSheet(None)
        # TODO implement dispense bills

    @pyqtSlot()
    def select1(self):
        # print(self.counter5)
        self.counter5 = self.counter5 + 1
        self.ui.amountBillsFive.setText(f"Aantal geselcteerd: {self.counter5}")
    
    @pyqtSlot()
    def select2(self):
        # print(self.counter10)
        self.counter10 = self.counter10 + 1
        self.ui.amountBillsTen.setText(f"Aantal geselcteerd: {self.counter10}")

    @pyqtSlot()
    def select3(self):
        # print(self.counter50)
        self.counter50 = self.counter50 + 1
        self.ui.amountBillsFifthy.setText(f"Aantal geselcteerd: {self.counter50}")

    @pyqtSlot()
    def deselect1(self):
        self.counter5 = self.counter5 -1
        self.ui.amountBillsFive.setText(f"Aantal geselcteerd: {self.counter5}")
    
    @pyqtSlot()
    def deselect2(self):
        self.counter10 = self.counter10 - 1
        self.ui.amountBillsTen.setText(f"Aantal geselcteerd: {self.counter10}")

    @pyqtSlot()
    def deselect3(self):
        self.counter50 = self.counter50 - 1
        self.ui.amountBillsFifthy.setText(f"Aantal geselcteerd: {self.counter50}")

    #
    # Donate page
    #
    @pyqtSlot()
    def donate(self):
        # TODO implement
        self.ui.stack.setCurrentIndex(self.RESULT_PAGE)
        self.ui.resultText.setText('Nog niet geïmplementeerd')
        self.timer = QTimer()
        self.timer.timeout.connect(self.abort)
        self.timer.setSingleShot(True)
        self.timer.start(2000)

# print usage information
def help():
    print('usage: gui.py [-h] [-s | --serial-port=] [-h | --host=] [-p | --port=]')

def main(argv):
    global app
    global hbp
    global arduino

    # parse command line options
    try:
        opts, args = getopt.getopt(argv, '?s:h:p:', [ 'serial-port=', 'host=', 'port=' ])
    except getopt.GetoptError:
        help()
        sys.exit(1)

    # empty input_souce means that we'll use only the keyboard and mouse as input
    serial_port = 'COM5'

    host = '145.24.222.242'
    port = 8420

    for opt, arg in opts:
        if opt == '-?':
            help()
            sys.exit(0)
        elif opt in ('-s', '--serial-port'):
            serial_port = arg
        elif opt in ('-h', '--host'):
            host = arg
        elif opt in ('-p', '--port'):
            port = arg

    print('Copyright (C) 2021 INGrid GUI v1.0')
    try:
        hbp = HBP(host, port)
    except ConnectionRefusedError:
        print(f'Failed to connect to {host}:{port}')
        exit(1)
    print(f'Connected to Herbank Server @ {host}:{port}')

    if serial_port != '':
        arduino = serial.Serial(serial_port, 9600, timeout=.1)

    app = QtWidgets.QApplication(sys.argv)

    win = MainWindow()
    win.showMaximized()
    sys.exit(app.exec())

if __name__ == "__main__":
    main(sys.argv[1:])
