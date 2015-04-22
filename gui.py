#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Program to loop videos based on timestamps in a text file
"""

import argparse
import json
import os
import sys
import traceback
from datetime import timedelta

import qtawesome as qta
from PyQt5 import uic
from PyQt5.QtWidgets import QApplication, QFileDialog, QMainWindow, \
    QMessageBox, QFrame, QSlider, QStyle, QStyleOptionSlider, QHeaderView, \
    QTableView, QDataWidgetMapper, QPlainTextEdit
from PyQt5.QtGui import QPalette, QColor, QWheelEvent, QKeyEvent, QPainter, \
    QPen
from PyQt5.QtCore import QTimer, pyqtSignal, Qt, QAbstractTableModel, QVariant, \
    QRect, QModelIndex

import vlc


class TimestampDelta(timedelta):
    def __new__(cls, *args, **kwargs):
        return super(TimestampDelta, cls).__new__(cls, *args, **kwargs)

    def __str__(self):
        mm, ss = divmod(self.seconds, 60)
        hh, mm = divmod(mm, 60)
        if self.days:
            hh += self.days * 24
        ms, _ = divmod(self.microseconds, 1000)
        s = "%d:%02d:%02d.%03d" % (hh, mm, ss, ms)
        return s

    @property
    def milliseconds(self):
        ms = self.seconds * 1000000
        if self.microseconds:
            ms += self.microseconds
        if self.days:
            ms += self.days * 24 * 60 * 60 * 100000
        return int(ms/1000)


class Timestamp():
    def __init__(self, start_time, end_time, description=None):
        self.start_time = TimestampDelta(milliseconds=start_time)
        self.end_time = TimestampDelta(milliseconds=end_time)
        self.description = description

    def get_displayed_start_time(self):
        return str(self.start_time)

    def get_displayed_end_time(self):
        return str(self.end_time)

    def get_string_value_from_index(self, index):
        return str(self.start_time) if index == 0 else str(self.end_time) if index == 1\
            else self.description

    def get_value_from_index(self, index):
        return self.start_time if index == 0 else self.end_time if index == 1 \
            else self.description

    def set_value_from_index(self, index, value):
        if index == 0:
            self.start_time = value
        elif index == 1:
            self.end_time = value
        elif index == 2:
            self.description = value

    def __repr__(self):
        return json.dumps({
            "start_time": str(self.start_time),
            "end_time": str(self.end_time),
            "description": self.description
        })


class TimestampList():
    HEADERS = [
        "Start Time",
        "End Time",
        "Description"
    ]

    def __init__(self, data=[]):
        self.list = []
        for timestamp in data:
            self.list.append(
                Timestamp(
                    timestamp['start_time'],
                    timestamp['end_time'],
                    timestamp['description']
                )
            )

    def append(self, timestamp):
        self.list.append(timestamp)

    def header_at_index(self, index):
        return TimestampList.HEADERS[index]

    def __len__(self):
        return len(self.list)

    def __getitem__(self, item):
        return self.list[item]

    def __str__(self):
        return str(self.list)

    def __repr__(self):
        return repr(self.list)


class TimestampModel(QAbstractTableModel):
    def __init__(self, input_file_location=None, parent=None):
        super(TimestampModel, self).__init__(parent)
        self.input_file_location = input_file_location
        self.list = TimestampList()

        if input_file_location:
            with open(self.input_file_location, "r+") as input_file:
                self.list = TimestampList(json.load(input_file))

    def rowCount(self, parent=None, *args, **kwargs):
        if parent and parent.isValid():
            return 0
        return len(self.list)

    def columnCount(self, parent=None, *args, **kwargs):
        if parent and parent.isValid():
            return 0
        return 3

    def data(self, index, role=None):
        if not index.isValid():
            return QVariant()
        if role == Qt.UserRole:
            return self.list[index.row()].get_value_from_index(index.column())
        if role != Qt.DisplayRole and role != Qt.EditRole:
            return QVariant()
        return self.list[index.row()].get_string_value_from_index(
            index.column())

    def headerData(self, col, orientation, role=None):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.list.header_at_index(col)
        return QVariant()

    def flags(self, index):
        if not index.isValid():
            return None
        return Qt.ItemIsEditable | Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def setData(self, index, content, role=Qt.EditRole):
        if not index.isValid() or role != Qt.EditRole:
            return False
        self.list[index.row()].set_value_from_index(index.column(), content)
        self.dataChanged.emit(index, index)
        return True


class TimestampTableView(QTableView):
    def __init__(self, parent=None):
        super(TimestampTableView, self).__init__(parent)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

    def mouseReleaseEvent(self, event):
        super(TimestampTableView, self).mouseReleaseEvent(event)
        index = self.indexAt(event.pos())
        if not index.isValid():
            self.selectionModel().clearSelection()


class VideoFrame(QFrame):
    double_clicked = pyqtSignal()
    wheel = pyqtSignal(QWheelEvent)
    key_pressed = pyqtSignal(QKeyEvent)

    def __init__(self, parent=None):
        QFrame.__init__(self, parent)

        self.original_parent = parent
        self.palette = self.palette()
        self.palette.setColor(QPalette.Window, QColor(0,0,0))

        self.setPalette(self.palette)
        self.setAutoFillBackground(True)

    def mouseDoubleClickEvent(self, _):
        self.double_clicked.emit()

    def wheelEvent(self, event):
        self.wheel.emit(event)

    def keyPressEvent(self, event):
        self.key_pressed.emit(event)


class HighlightedJumpSlider(QSlider):
    def __init__(self, parent=None):
        super(HighlightedJumpSlider, self).__init__(parent)
        self.highlight_start = None
        self.highlight_end = None

    def mousePressEvent(self, ev):
        """ Jump to click position """
        self.setValue(QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), ev.x(), self.width())
        )

    def mouseMoveEvent(self, ev):
        """ Jump to pointer position while moving """
        self.setValue(QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), ev.x(), self.width())
        )

    def set_highlight(self, start, end):
        if start and end and start < end:
            self.highlight_start, self.highlight_end = start, end

    def paintEvent(self, event):
        if self.highlight_start and self.highlight_end:
            p = QPainter(self)
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            gr = self.style().subControlRect(QStyle.CC_Slider, opt,
                                             QStyle.SC_SliderGroove, self)
            rect_x, rect_y, rect_w, rect_h = gr.getRect()
            start_x = int(
                (rect_w/(self.maximum() - self.minimum()))
                * self.highlight_start + rect_x
            )
            start_y = rect_y + 3
            width = int(
                (rect_w/(self.maximum() - self.minimum()))
                * self.highlight_end + rect_x
            ) - start_x
            height = rect_h - 3
            c = QColor(0, 152, 116)
            p.setBrush(c)
            c.setAlphaF(0.3)
            p.setPen(QPen(c, 1.0))
            rect_to_paint = QRect(start_x, start_y, width, height)
            p.drawRects(rect_to_paint)
        super(HighlightedJumpSlider, self).paintEvent(event)


class PlainTextEdit(QPlainTextEdit):
    """
    For some reason Qt refuses to style readOnly QPlainTextEdit correctly, so
    this class is a workaround for that
    """
    def setReadOnly(self, read_only):
        super(PlainTextEdit, self).setReadOnly(read_only)
        if read_only:
            self.setStyleSheet("QPlainTextEdit {"
                               "background-color: #F0F0F0;"
                               "color: #808080;"
                               "border: 1px solid #B0B0B0;"
                               "border-radius: 2px;"
                               "}")
        elif not read_only:
            self.setStyleSheet("QPlainTextEdit {"
                               "background-color: #FFFFFF;"
                               "color: #000000;"
                               "border: 1px solid #B0B0B0;"
                               "border-radius: 2px;"
                               "}")


class MainWindow(QMainWindow):
    """
    The main window class
    """
    def __init__(self, parent=None):
        QMainWindow.__init__(self, parent)
        self.ui = uic.loadUi("main_window.ui")

        self.timestamp_filename = None
        self.video_filename = None
        self.media_start_time = None
        self.media_end_time = None
        self.restart_needed = False
        self.timer_period = 100
        self.is_full_screen = False
        self.media_started_playing = False
        self.media_is_playing = False
        self.original_window_flags = None
        self.mute = False

        self.model = TimestampModel(None, self)
        self.ui.list_timestamp.setModel(self.model)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_ui)
        self.timer.timeout.connect(self.timer_handler)
        self.timer.start(self.timer_period)

        self.ui.button_run.clicked.connect(self.run)
        self.ui.button_timestamp_browse.clicked.connect(
            self.browse_timestamp_handler
        )
        self.ui.button_video_browse.clicked.connect(
            self.browse_video_handler
        )
        self.vlc_instance = vlc.Instance()
        self.media_player = self.vlc_instance.media_player_new()
        # if sys.platform == "darwin":  # for MacOS
        #     self.ui.frame_video = QMacCocoaViewContainer(0)
        self.ui.frame_video.double_clicked.connect(self.toggle_full_screen)
        self.ui.frame_video.wheel.connect(self.wheel_handler)
        self.ui.frame_video.key_pressed.connect(self.key_handler)
        self.ui.button_play_pause.clicked.connect(self.play_pause)
        self.ui.button_full_screen.clicked.connect(self.toggle_full_screen)
        self.ui.button_speed_up.clicked.connect(self.speed_up_handler)
        self.ui.button_slow_down.clicked.connect(self.slow_down_handler)
        self.ui.button_mute_toggle.clicked.connect(self.toggle_mute)
        self.ui.slider_progress.setTracking(False)
        self.ui.slider_progress.valueChanged.connect(self.set_media_position)
        self.ui.slider_volume.valueChanged.connect(self.set_volume)
        self.ui.entry_description.setReadOnly(True)
        # Set up some icons
        self.set_up_play_pause_button()
        self.ui.button_play_pause.setText("")
        self.ui.button_speed_up.setIcon(
            qta.icon("fa.arrow-circle-o-up", scale_factor=0.8)
        )
        self.ui.button_speed_up.setText("")
        self.ui.button_slow_down.setIcon(
            qta.icon("fa.arrow-circle-o-down", scale_factor=0.8)
        )
        self.ui.button_slow_down.setText("")
        self.ui.button_full_screen.setIcon(
            qta.icon("ei.fullscreen", scale_factor=0.6)
        )
        self.ui.button_full_screen.setText("")
        self.toggle_mute_button()
        self.ui.button_mute_toggle.setText("")
        # Mapper between the table and the entry detail
        self.mapper = QDataWidgetMapper()
        self.mapper.setSubmitPolicy(QDataWidgetMapper.ManualSubmit)
        self.mapper.setModel(self.model)
        self.mapper.addMapping(self.ui.entry_start_time, 0)
        self.mapper.addMapping(self.ui.entry_end_time, 1)
        self.mapper.addMapping(self.ui.entry_description, 2)
        self.ui.button_save.clicked.connect(self.mapper.submit)
        # Set up default volume
        self.set_volume(self.ui.slider_volume.value())
        self.vlc_events = self.media_player.event_manager()
        self.vlc_events.event_attach(
            vlc.EventType.MediaPlayerTimeChanged, self.media_time_change_handler
        )
        self.media_player.video_set_mouse_input(False)
        self.media_player.video_set_key_input(False)
        self.ui.show()

    def set_media_position(self, position):
        self.media_player.set_position(position / 10000.0)
        self.media_end_time = -1

    def update_ui(self):
        self.ui.slider_progress.blockSignals(True)
        self.ui.slider_progress.setValue(
            self.media_player.get_position() * 10000
        )
        self.ui.slider_progress.blockSignals(False)

    def timer_handler(self):
        """
        This is a workaround, because for some reason we can't call set_time()
        inside the MediaPlayerTimeChanged handler (as the video just stops
        playing)
        """
        if self.restart_needed:
            self.media_player.set_time(self.media_start_time)
            self.restart_needed = False

    def key_handler(self, event):
        if event.key() == Qt.Key_Escape and self.is_full_screen:
            self.toggle_full_screen()
        if event.key() == Qt.Key_F:
            self.toggle_full_screen()
        if event.key() == Qt.Key_Space:
            self.play_pause()

    def wheel_handler(self, event):
        self.modify_volume(1 if event.angleDelta().y() > 0 else -1)

    def toggle_mute(self):
        self.media_player.audio_set_mute(not self.media_player.audio_get_mute())
        self.mute = not self.mute
        self.toggle_mute_button()

    def toggle_mute_button(self):
        if self.mute:
            self.ui.button_mute_toggle.setIcon(
                qta.icon("fa.volume-off", scale_factor=0.8)
            )
        else:
            self.ui.button_mute_toggle.setIcon(
                qta.icon("fa.volume-up", scale_factor=0.8)
            )

    def modify_volume(self, delta_percent):
        new_volume = self.media_player.audio_get_volume() + delta_percent
        if new_volume < 0:
            new_volume = 0
        elif new_volume > 40:
            new_volume = 40
        self.media_player.audio_set_volume(new_volume)
        self.ui.slider_volume.setValue(self.media_player.audio_get_volume())

    def set_volume(self, new_volume):
        self.media_player.audio_set_volume(new_volume)

    def speed_up_handler(self):
        self.modify_rate(0.1)

    def slow_down_handler(self):
        self.modify_rate(-0.1)

    def modify_rate(self, delta_percent):
        new_rate = self.media_player.get_rate() + delta_percent
        if new_rate < 0.2 or new_rate > 2.0:
            return
        self.media_player.set_rate(new_rate)

    def media_time_change_handler(self, _):
        if self.media_end_time == -1:
            return
        if self.media_player.get_time() > self.media_end_time:
            self.restart_needed = True

    def run(self):
        """
        Execute the loop
        """
        if self.timestamp_filename is None:
            self._show_error("No timestamp file chosen")
            return
        if self.video_filename is None:
            self._show_error("No video file chosen")
            return
        try:
            if self.ui.list_timestamp.selectionModel().hasSelection():
                selected_row = self.ui.list_timestamp.selectionModel().\
                    selectedRows()[0]
                start_delta = self.ui.list_timestamp.model().data(
                    selected_row.model().index(selected_row.row(), 0),
                    Qt.UserRole
                )
                end_delta = self.ui.list_timestamp.model().data(
                    selected_row.model().index(selected_row.row(), 1),
                    Qt.UserRole
                )
                duration = self.media_player.get_media().get_duration()
                self.media_start_time = start_delta.milliseconds
                self.media_end_time = end_delta.milliseconds
                slider_start_pos = (self.media_start_time / duration) * (self.ui.slider_progress.maximum() - self.ui.slider_progress.minimum())
                slider_end_pos = (self.media_end_time / duration) * (self.ui.slider_progress.maximum() - self.ui.slider_progress.minimum())
                self.ui.slider_progress.set_highlight(
                    int(slider_start_pos), int(slider_end_pos)
                )

            else:
                self.media_start_time = 0
                self.media_end_time = -1
            self.media_player.play()
            self.media_player.set_time(self.media_start_time)
            self.media_started_playing = True
            self.media_is_playing = True
            self.set_up_play_pause_button()
        except Exception as ex:
            self._show_error(str(ex))
            print(traceback.format_exc())

    def play_pause(self):
        """Toggle play/pause status
        """
        if not self.media_started_playing:
            self.run()
            return
        if self.media_is_playing:
            self.media_player.pause()
        else:
            self.media_player.play()
        self.media_is_playing = not self.media_is_playing
        self.set_up_play_pause_button()

    def set_up_play_pause_button(self):
        if not self.media_is_playing:
            self.ui.button_play_pause.setIcon(
                qta.icon("fa.play", scale_factor=0.7)
            )
        else:
            self.ui.button_play_pause.setIcon(
                qta.icon("fa.pause", scale_factor=0.7)
            )

    def toggle_full_screen(self):
        if self.is_full_screen:
            self.ui.frame_media.showNormal()
            self.ui.frame_media.setParent(self.ui.widget_central)
            self.ui.frame_media.resize(self.original_size)
            self.ui.frame_media.overrideWindowFlags(self.original_window_flags)
            self.ui.layout_main.addWidget(self.ui.frame_media, 2, 3, 3, 1)
            self.ui.frame_media.show()
        else:
            self.original_window_flags = self.ui.frame_media.windowFlags()
            self.original_size = self.ui.frame_media.size()
            self.ui.frame_media.setParent(None)
            self.ui.frame_media.setWindowFlags(Qt.FramelessWindowHint |
                                               Qt.CustomizeWindowHint)
            self.ui.frame_media.showFullScreen()
            self.ui.frame_media.show()
        self.ui.frame_video.setFocus()
        self.is_full_screen = not self.is_full_screen

    def browse_timestamp_handler(self):
        """
        Handler when the timestamp browser button is clicked
        """
        tmp_name, _ = QFileDialog.getOpenFileName(
            self, "Choose Timestamp file", None,
            "Timestamp File (*.tmsp);;All Files (*)"
        )
        if not tmp_name:
            return
        self.set_timestamp_filename(tmp_name)

    def set_timestamp_filename(self, filename):
        """
        Set the timestamp file name
        """
        if not os.path.isfile(filename):
            self._show_error("Cannot access timestamp file " + filename)
            return
        self.timestamp_filename = filename
        self.ui.entry_timestamp.setText(self.timestamp_filename)

        self.model = TimestampModel(self.timestamp_filename, self)
        self.ui.list_timestamp.setModel(self.model)
        self.mapper.setModel(self.model)
        self.mapper.addMapping(self.ui.entry_start_time, 0)
        self.mapper.addMapping(self.ui.entry_end_time, 1)
        self.mapper.addMapping(self.ui.entry_description, 2)
        self.ui.list_timestamp.selectionModel().selectionChanged.connect(
            self.timestamp_selection_changed)

        directory = os.path.dirname(self.timestamp_filename)
        basename = os.path.basename(self.timestamp_filename)
        timestamp_name_without_ext = os.path.splitext(basename)[0]
        for file_in_dir in os.listdir(directory):
            current_filename = os.path.splitext(file_in_dir)[0]
            found_video = (current_filename == timestamp_name_without_ext and
                           file_in_dir != basename)
            if found_video:
                found_video_file = os.path.join(directory, file_in_dir)
                self.set_video_filename(found_video_file)
                break

    def timestamp_selection_changed(self, selected, deselected):
        if len(selected) > 0:
            self.mapper.setCurrentModelIndex(selected.indexes()[0])
            self.ui.button_save.setEnabled(True)
            self.ui.entry_start_time.setReadOnly(False)
            self.ui.entry_end_time.setReadOnly(False)
            self.ui.entry_description.setReadOnly(False)
        else:
            self.mapper.setCurrentModelIndex(QModelIndex())
            self.ui.button_save.setEnabled(False)
            self.ui.entry_start_time.clear()
            self.ui.entry_end_time.clear()
            self.ui.entry_description.clear()
            self.ui.entry_start_time.setReadOnly(True)
            self.ui.entry_end_time.setReadOnly(True)
            self.ui.entry_description.setReadOnly(True)

    def set_video_filename(self, filename):
        """
        Set the video filename
        """
        if not os.path.isfile(filename):
            self._show_error("Cannot access video file " + filename)
            return

        self.video_filename = filename

        media = self.vlc_instance.media_new(self.video_filename)
        media.parse()
        if not media.get_duration():
            self._show_error("Cannot play this media file")
            self.media_player.set_media(None)
            self.video_filename = None
        else:
            self.media_player.set_media(media)
            if sys.platform.startswith('linux'): # for Linux using the X Server
                self.media_player.set_xwindow(self.ui.frame_video.winId())
            elif sys.platform == "win32": # for Windows
                self.media_player.set_hwnd(self.ui.frame_video.winId())
            elif sys.platform == "darwin": # for MacOS
                self.media_player.set_nsobject(self.ui.frame_video.winId())
            self.ui.entry_video.setText(self.video_filename)
            self.media_started_playing = False
            self.media_is_playing = False
            self.set_up_play_pause_button()

    def browse_video_handler(self):
        """
        Handler when the video browse button is clicked
        """
        tmp_name, _ = QFileDialog.getOpenFileName(
            self, "Choose Video file", None,
            "All Files (*)"
        )
        if not tmp_name:
            return
        self.set_video_filename(tmp_name)

    def _show_error(self, message, title="Error"):
        QMessageBox.warning(self, title, message)


def main():
    """
    Main function for the program
    """
    parser = argparse.ArgumentParser(
        description="Loop a video between 2 points in time based on rules in "
                    "a text file."
    )
    parser.add_argument('timestamp_filename', metavar='F', nargs='?',
                        help='the location of the timestamp file')
    parser.add_argument('--video_filename', metavar='V',
                        help='the location of the video file')
    args = parser.parse_args()
    app = QApplication(sys.argv)
    with open("application.qss", "r") as theme_file:
        app.setStyleSheet(theme_file.read())
    main_window = MainWindow()

    if args.timestamp_filename:
        timestamp_filename = os.path.abspath(args.timestamp_filename)
        main_window.set_timestamp_filename(timestamp_filename)
    if args.video_filename:
        video_filename = os.path.abspath(args.video_filename)
        main_window.set_video_filename(video_filename)

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
