import subprocess
from time import sleep

from Xlib import Xatom, X
from Xlib.display import Display

from Xlib.error import BadWindow
from chromote import Chromote
from kivy.clock import Clock

from kivy.core.window import Window, WindowBase
from kivy.properties import StringProperty
from kivy.uix.widget import Widget


def locate_chromium_binary():
    # check RPi name
    out, err = subprocess.Popen(['which','chromium-browser'], stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()

    # else check linux desktop name
    if err:
        out, err = subprocess.Popen(['which', 'chromium'], stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()

    if err:
        raise RuntimeError('Chromium not found.')

    return out.decode().strip()

CHROMIUM_BIN = locate_chromium_binary()


def print_xlib_tree(root, level=0):
    print('\t'*level, root.id, root.get_wm_class(), root.get_wm_name(), root.get_full_property(root.display.get_atom('WM_WINDOW_ROLE'), Xatom.STRING))

    for c in root.query_tree().children:
        print_xlib_tree(c, level+1)


def walk_xlib_windows(root):
    yield root

    for child in root.query_tree().children:
        yield child


# TODO : figure out of async works with kivy
def awaitish(func, delay=0.2, timeout=30):
    for _ in range(int(timeout/delay)):
        rv = func()

        if rv:
            return rv

        sleep(delay)


class XWrapChromium(Widget):
    # command = StringProperty()

    _free_ports = []
    _next_port = 9222

    _is_visible = None

    def __init__(self, start_url=None, **kwargs):
        super().__init__(**kwargs)

        # TODO : actually return ports to _free_ports
        try:
            self.chromote_port = XWrapChromium._free_ports.pop()
        except IndexError:
            self.chromote_port = XWrapChromium._next_port
            XWrapChromium._next_port += 1

        chromium_command = [
            CHROMIUM_BIN,
            '--incognito',
            '--bwsi',
            '--kiosk',
            '--no-default-browser-check',
            '--no-first-run',
            '--no-session-id',
            '--new-window',
            '--user-data-dir=/tmp/chromote{}'.format(self.chromote_port),
            '--remote-debugging-port={}'.format(self.chromote_port),
            '--class=XWrap{}'.format(self.chromote_port),
            start_url or 'about:blank',
        ]

        print(chromium_command)

        self.process = subprocess.Popen(chromium_command)
        self.xdisplay = Display()
        self.xroot = self.xdisplay.screen().root

        # TODO : don't block everything while waiting.. also make it adaptable to non-chromium? (no probably not)
        self.xwindow = None  # set to None first so update_window(..) doesn't break if fired early by Kivy.
        self.xwindow = awaitish(lambda: self.find_chromium())
        self.xwindow.unmap()

        self.chromote = Chromote('localhost', self.chromote_port)

        print('Found Window: {}'.format(self.xwindow.id))
        self.update_xwindow()
        self.bind(pos=self.__class__.handle_move, size=self.__class__.handle_resize)

        Clock.schedule_interval(self.check_visible, 1/10.0)
        print_xlib_tree(self.xdisplay.screen().root)

        kroot = self.parent
        self.kivy_root = None

        while kroot:
            if isinstance(kroot, WindowBase):
                self.kivy_root = kroot
                kroot.bind(pos=self.__class__.handle_move, size=self.__class__.handle_resize)
                break

            kroot = kroot.parent

    @property
    def is_visible(self):
        # No other way to determine visibility of widget other than to check path to root window
        kroot = self.parent

        while kroot:
            if isinstance(kroot, WindowBase):
                self.kivy_root = kroot
                return True

            kroot = kroot.parent

        return False

    def check_visible(self, *args, **kwargs):
        if not self.xwindow or not self.xroot:
            return

        # toggle invis -> vis
        if not self._is_visible and self.is_visible:
            self._is_visible = True
            self.xwindow.map()
            self.xdisplay.sync()

        # toggle vis -> invis
        elif self._is_visible and not self.is_visible:
            self._is_visible = False
            self.xwindow.unmap()
            self.xdisplay.sync()

        if self._is_visible:
            self.xwindow.raise_window()

    def yield_wm_pid(self, pid, root=None):
        if root is None:
            root = self.xdisplay.screen().root

        net_wm_pid = root.display.get_atom('_NET_WM_PID')

        for w in walk_xlib_windows(root):
            prop = w.get_full_property(net_wm_pid, Xatom.CARDINAL)

            if prop and prop.value[0] == pid:
                yield w

    def find_chromium(self):
        for w in self.yield_wm_pid(self.process.pid):
            prop = w.get_full_property(w.display.get_atom('WM_WINDOW_ROLE'), Xatom.STRING)

            if prop and prop.value == b'browser':
                return w

    def find_wm_class(self, wm_name, root=None):
        if root is None:
            root = self.xdisplay.screen().root

        for w in walk_xlib_windows(root):
            try:
                cls = w.get_wm_class()
            except BadWindow:
                continue

            if cls and cls[1] == wm_name:
                return w

    def handle_resize(self, new_size):
        self.update_xwindow()

    def handle_move(self, new_loc):
        self.update_xwindow()

    def update_xwindow(self, *args, **kwargs):
        if self.xwindow is None:
            return

        # print('Reconfiguring child_window - pos: %r  size: %r', self.child_window, self.pos, self.size)
        self.xwindow.configure(
            x=int(self.pos[0] + Window.left),
            y=int(((Window.top + Window.height) - (self.size[1] + self.pos[1]))),
            width=int(self.size[0]),
            height=int(self.size[1]),
            stack_mod=X.Above
        )

        self.check_visible()
        self.xdisplay.sync()


if __name__ == '__main__':
    from kivy.app import App
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.button import Button
    from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem

    import random

    random_sites = [
        'http://html5zombo.com',
        'http://reddit.com',
        'http://imgur.com',
        'http://news.ycombinator.com',
        'http://google.com',
        'http://yahoo.com',
        'http://altavista.com',
        'http://wikipedia.org'
    ]


    class TestApp(App):
        def build(self):
            tp = TabbedPanel(do_default_tab=False)
            tab0 = TabbedPanelItem(text='First Tab')

            box = BoxLayout(orientation='horizontal', padding=5)
            xw0 = XWrapChromium('http://news.ycombinator.com')

            box.add_widget(xw0)

            b = Button(text='Randomize Site')
            b.bind(on_press=lambda inst: xw0.chromote.tabs[0].set_url(random.choice(random_sites)))
            box.add_widget(b)
            tab0.add_widget(box)

            tp.add_widget(tab0)

            tab1 = TabbedPanelItem(text='Other Panel')
            new_box = BoxLayout(orientation='vertical', padding=12)
            xw1 = XWrapChromium('http://codewaffle.com/')
            xw2 = XWrapChromium('http://eventual.games')

            b2 = Button(text='Random Sites')

            def randomize_xw12(*args, **kwargs):
                xw1.chromote.tabs[0].set_url(random.choice(random_sites))
                xw2.chromote.tabs[0].set_url(random.choice(random_sites))

            b2.bind(on_press=randomize_xw12)

            new_box.add_widget(xw1)
            new_box.add_widget(b2)
            new_box.add_widget(xw2)
            tab1.add_widget(new_box)
            tp.add_widget(tab1)

            return tp

    TestApp().run()
