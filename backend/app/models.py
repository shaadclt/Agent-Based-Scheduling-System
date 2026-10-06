from datetime import datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)

from sqlalchemy.orm import relationship

from backend.app.database import Base


# ============================================================
# Doctor
# ============================================================

class Doctor(Base):

    __tablename__ = "doctors"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    name = Column(
        String(150),
        nullable=False,
        unique=True,
    )

    specialty = Column(
        String(100),
        nullable=False,
        index=True,
    )

    experience = Column(
        Integer,
        nullable=False,
    )

    description = Column(
        Text,
        nullable=True,
    )

    appointments = relationship(
        "Appointment",
        back_populates="doctor",
    )

    availability = relationship(
        "DoctorAvailability",
        back_populates="doctor",
    )


# ============================================================
# Patient
# ============================================================

class Patient(Base):

    __tablename__ = "patients"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    name = Column(
        String(150),
        nullable=False,
    )

    appointments = relationship(
        "Appointment",
        back_populates="patient",
    )


# ============================================================
# Doctor Availability
# ============================================================

class DoctorAvailability(Base):

    __tablename__ = "doctor_availability"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    doctor_id = Column(
        Integer,
        ForeignKey("doctors.id"),
        nullable=False,
    )

    date = Column(
        Date,
        nullable=False,
        index=True,
    )

    start_time = Column(
        Time,
        nullable=False,
    )

    end_time = Column(
        Time,
        nullable=False,
    )

    doctor = relationship(
        "Doctor",
        back_populates="availability",
    )


# ============================================================
# Appointment
# ============================================================

class Appointment(Base):

    __tablename__ = "appointments"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    patient_id = Column(
        Integer,
        ForeignKey("patients.id"),
        nullable=False,
    )

    doctor_id = Column(
        Integer,
        ForeignKey("doctors.id"),
        nullable=False,
    )

    appointment_date = Column(
        Date,
        nullable=False,
        index=True,
    )

    appointment_time = Column(
        Time,
        nullable=False,
    )

    status = Column(
        String(30),
        nullable=False,
        default="confirmed",
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
    )

    patient = relationship(
        "Patient",
        back_populates="appointments",
    )

    doctor = relationship(
        "Doctor",
        back_populates="appointments",
    )

    __table_args__ = (
        UniqueConstraint(
            "doctor_id",
            "appointment_date",
            "appointment_time",
            name="unique_doctor_appointment",
        ),
    )